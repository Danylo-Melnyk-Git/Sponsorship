"""Authenticated ASGI adapter. One organization, shared research visibility."""
import hmac
import json
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, RedirectResponse
from starlette.routing import Route
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.server import ASSETS, WEB, summary, jobs_meta, jobs_overview
from packages.domain.service import ResearchService
from packages.domain.storage import open_store as Store
from packages.domain.models import ConflictError
from packages.runtime.auth import AuthStore, AccessError
from packages.runtime.config import Settings
from packages.runtime.permissions import permit, action_payload
from packages.runtime.jobs import JobStore
from packages.runtime.research_jobs import ResearchJobs
from packages.domain.reporting import markdown
from packages.domain.pdf_export import pdf_bytes, PDFUnavailable
from packages.strategy.engine import strategy
from packages.strategy.report import html

LOGIN = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Вход · Sponsorship</title><link rel="stylesheet" href="/styles.css"><script src="/login.js" defer></script><main class="panel"><h1>Вход в Sponsorship</h1><form id="login"><label>Логин <input name="username" autocomplete="username" required></label><label>Пароль <input name="password" type="password" autocomplete="current-password" required></label><button>Войти</button><p id="error" role="alert"></p></form></main></html>'''
LOGIN_JS = '''document.querySelector('#login').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(f))});if(r.ok)location.assign('/');else document.querySelector('#error').textContent=(await r.json()).error;});'''


def create_app(settings=None):
    settings = settings or Settings.from_env()
    auth = AuthStore(settings.auth_database)
    service = ResearchService(Store(settings.database))
    jobs = ResearchJobs(JobStore(settings.jobs_database), service, settings.search_provider, settings.daily_jobs)

    async def endpoint(request):
        try:
            if request.url.path == "/healthz" and request.method == "GET":
                return JSONResponse({"status": "ok"})
            if request.headers.get("host") != urlsplit(settings.public_url).netloc:
                raise AccessError("Неверный Host", 400)
            method, path = request.method, request.url.path
            body = None
            if method == "POST":
                if request.headers.get("origin") != settings.public_url:
                    raise AccessError("Неверный Origin")
                if request.headers.get("content-type", "").split(";")[0] != "application/json":
                    raise AccessError("Ожидается JSON", 400)
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 524288:
                        raise AccessError("Запрос слишком большой", 413)
                body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(body, dict):
                    raise ValueError("Нужен JSON объект")
            if path in ("/login", "/login.js") and method == "GET":
                return Response(LOGIN if path == "/login" else LOGIN_JS, media_type="text/html" if path == "/login" else "text/javascript")
            if path in ("/styles.css", "/favicon.svg") and method == "GET":
                name, mime = ASSETS[path]
                return Response((WEB/name).read_bytes(), media_type=mime.split(";")[0])
            if path == "/auth/login" and method == "POST":
                token, _ = await run_in_threadpool(auth.login, body.get("username"), body.get("password"), settings.session_hours)
                response = JSONResponse({"ok": True})
                response.set_cookie(settings.cookie_name, token, max_age=settings.session_hours*3600, httponly=True, secure=settings.secure, samesite="strict", path="/")
                return response
            token = request.cookies.get(settings.cookie_name, "")
            try:
                user = auth.session(token)
            except AccessError:
                if path == "/" and method == "GET":
                    return RedirectResponse("/login", status_code=303)
                raise
            if method == "POST" and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf"]):
                raise AccessError("Неверный CSRF token")
            if path == "/auth/me":
                return JSONResponse(user)
            if path == "/auth/logout" and method == "POST":
                auth.logout(token)
                response = JSONResponse({"ok": True})
                response.delete_cookie(settings.cookie_name, path="/", secure=settings.secure, httponly=True, samesite="strict")
                return response
            if method == "GET" and path in ASSETS:
                name, mime = ASSETS[path]
                return Response((WEB/name).read_bytes(), media_type=mime.split(";")[0])
            if path == "/api/meta" and method == "GET":
                from packages.domain.models import STAGES, STAGE_LABELS, GOALS, KINDS, CRITERIA, RISK_STATUSES, TASK_STATUSES, METRICS
                from packages.scoring.engine import PROFILES, MODEL_VERSION, WEIGHTS_DATE, WEIGHTS_STATUS
                from packages.domain.agents import configuration
                from packages.domain.activation import catalog
                from packages.domain.quality import METHODS
                return JSONResponse(dict(version="0.4-hosted", stages=list(zip(STAGES, STAGE_LABELS)), goals=GOALS, kinds=KINDS, criteria=CRITERIA, profiles=PROFILES, weights_status=f"{WEIGHTS_STATUS}, {WEIGHTS_DATE}", model_version=MODEL_VERSION, model_status="unvalidated",risk_statuses=RISK_STATUSES,task_statuses=TASK_STATUSES,metrics=METRICS,roles=configuration()["roles"],activation_catalog=catalog(),measurement_methods=METHODS,mode="hosted_single_organization",**jobs_meta(jobs)))
            if path == "/api/research":
                if method == "GET":
                    return JSONResponse([summary(s) for s in service.store.list()])
                permit(user, ("admin", "approver", "researcher", "reviewer"))
                state = service.create(body)
                auth.audit(user["username"], "create_research", state["id"])
                return JSONResponse(service.view(state["id"]), status_code=201)
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[:2] == ["api", "research"]:
                rid = parts[2]
                if len(parts) == 3 and method == "GET":
                    return JSONResponse(service.view(rid))
                if len(parts) == 4 and parts[3] == "actions" and method == "POST":
                    state = service.store.get(rid)
                    payload = action_payload(user, state, body.get("action"), body.get("payload"))
                    service.act(rid, body.get("revision"), body.get("action"), payload, "user:"+user["username"])
                    auth.audit(user["username"], "action:"+body["action"], rid)
                    return JSONResponse(service.view(rid))
                if len(parts) >= 4 and parts[3] == "jobs":
                    if len(parts) == 4 and method == "GET":
                        return JSONResponse(jobs_overview(jobs, service, rid))
                    permit(user, ("admin", "approver", "researcher", "reviewer"))
                    if len(parts) == 4 and method == "POST":
                        job = await run_in_threadpool(jobs.enqueue, rid, user["username"], body.get("idempotency_key"),
                                                      body.get("plan_query_id"), body.get("confirm_paid") is True)
                        auth.audit(user["username"], "enqueue_search", rid)
                        return JSONResponse(job, status_code=201)
                    if len(parts) == 6 and parts[5] == "cancel" and method == "POST":
                        jobs.cancel(rid, parts[4])
                        auth.audit(user["username"], "cancel_job", rid)
                        return JSONResponse(jobs.overview(rid))
                if method == "GET":
                    state = service.store.get(rid)
                    if len(parts) == 4 and parts[3] == "history": return JSONResponse(service.store.history(rid))
                    if len(parts) == 4 and parts[3] == "export": return Response(markdown(state), media_type="text/markdown")
                    if len(parts) == 4 and parts[3] == "export.pdf":
                        try: data = pdf_bytes(markdown(state), "Отчёт Sponsorship")
                        except PDFUnavailable as exc: return JSONResponse({"error": str(exc)}, status_code=503)
                        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{rid}.pdf"'})
                    if len(parts) == 4 and parts[3] == "strategy": return Response(html(strategy(state), style_href="/strategy.css"), media_type="text/html")
                    if len(parts) == 4 and parts[3] == "handoff":
                        from packages.domain.quality import readiness, handoff_markdown
                        return Response(handoff_markdown(readiness(state)), media_type="text/markdown")
                    if len(parts) == 4 and parts[3] == "handoff.pdf":
                        from packages.domain.quality import readiness, handoff_markdown
                        try: data = pdf_bytes(handoff_markdown(readiness(state)), "Пакет для отделов")
                        except PDFUnavailable as exc: return JSONResponse({"error": str(exc)}, status_code=503)
                        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{rid}-handoff.pdf"'})
                    if len(parts) == 5 and parts[3] == "agent":
                        from packages.domain.agents import role_task
                        return JSONResponse(role_task(state, parts[4]))
            return JSONResponse({"error": "Маршрут недоступен"}, status_code=404)
        except AccessError as exc: return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except ConflictError as exc: return JSONResponse({"error": str(exc)}, status_code=409)
        except PDFUnavailable as exc: return JSONResponse({"error": str(exc)}, status_code=503)
        except (ValueError, KeyError) as exc: return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception: return JSONResponse({"error": "Ошибка сервера; проверьте конфигурацию"}, status_code=500)

    app = Starlette(routes=[Route("/{path:path}", endpoint, methods=["GET", "POST"])])
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers.update({"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff", "Referrer-Policy":"no-referrer", "Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        if settings.secure: response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response
    app.add_middleware(BaseHTTPMiddleware, dispatch=headers)
    return app
