"""Local single-user server. Outbound search runs only in the background worker when configured."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from packages.domain.agents import configuration, role_task
from packages.domain.demo import seed
from packages.domain.models import (CRITERIA, GOALS, KINDS, METRICS, RISK_STATUSES, STAGES,
                                   STAGE_LABELS, TASK_STATUSES, ConflictError, ValidationError)
from packages.domain.reporting import markdown
from packages.domain.pdf_export import pdf_bytes, PDFUnavailable
from packages.scoring.engine import MODEL_VERSION, PROFILES
from packages.scoring.weights import WEIGHTS_DATE, WEIGHTS_STATUS
from packages.domain.activation import catalog
from packages.domain.quality import METHODS, readiness, handoff_markdown
from packages.strategy.engine import strategy
from packages.strategy import report as strategy_report
from packages.runtime.research_jobs import provider_status

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/strategy.css": ("strategy.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


def summary(state):
    return {key: state[key] for key in ("id", "title", "kind", "stage", "revision", "created_at", "updated_at")} | {
        "company": state["brief"]["company"], "candidates": len(state["candidates"]),
        "selected": sum(c["selected"] for c in state["candidates"]), "closed": state["case"] is not None,
    }


def jobs_meta(jobs):
    status = jobs.status() if jobs else provider_status("disabled")
    return {"automatic_research": status["available"], "research_jobs": status}


def jobs_overview(jobs, service, research_id):
    if jobs is None:
        service.store.get(research_id)
        status = provider_status("disabled")
        return {"provider": status, "jobs": [], "queries": [], "can_enqueue": False, "blocked": status["message"]}
    return jobs.overview(research_id)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service, jobs=None):
        if address[0] not in ("127.0.0.1", "localhost"):
            raise ValidationError("Локальный MVP слушает только loopback")
        self.service = service
        self.jobs = jobs
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "SponsorshipLocal/0.3"
    max_body = 512 * 1024

    def log_message(self, format, *args):
        pass

    def send(self, status, data, content_type="application/json; charset=utf-8", filename=None):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed_hosts:
            raise ValidationError("Неверный адрес локального сервера")
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in allowed_hosts}:
            raise ValidationError("Запрос с другого сайта отклонён")

    def body(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValidationError("Ожидается application/json")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValidationError("Неверный размер запроса") from exc
        if not 0 < size <= self.max_body:
            raise ValidationError("Пустой или слишком большой запрос")
        try:
            value = json.loads(self.rfile.read(size).decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValidationError("Неверный JSON") from exc
        if not isinstance(value, dict):
            raise ValidationError("JSON должен быть объектом")
        return value

    def dispatch(self, method):
        self.local_request()
        path = urlparse(self.path).path
        service = self.server.service
        if method == "GET" and path in ASSETS:
            name, content_type = ASSETS[path]
            return self.send(200, (WEB / name).read_bytes(), content_type)
        if method == "GET" and path == "/api/meta":
            return self.send(200, {"version": "0.3.0", "stages": list(zip(STAGES, STAGE_LABELS)),
                                   "goals": GOALS, "kinds": KINDS, "criteria": CRITERIA,
                                   "profiles": PROFILES, "weights_status": f"{WEIGHTS_STATUS}, {WEIGHTS_DATE}", "model_version": MODEL_VERSION,
                                   "model_status": "unvalidated", "risk_statuses": RISK_STATUSES,
                                   "task_statuses": TASK_STATUSES, "metrics": METRICS,
                                   "roles": configuration()["roles"],
                                   "activation_catalog": catalog(), "measurement_methods": METHODS,
                                   "mode": "local_single_user", **jobs_meta(self.server.jobs)})
        if path == "/api/research":
            if method == "GET":
                return self.send(200, [summary(s) for s in service.store.list()])
            if method == "POST":
                return self.send(201, service.view(service.create(self.body())["id"]))
        if path == "/api/demo" and method == "POST":
            self.body()
            return self.send(201, service.view(seed(service)["id"]))
        if path == "/api/activation" and method == "POST":
            return self.send(201, service.view(service.create_signed(self.body())["id"]))
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "research"]:
            research_id = parts[2]
            if len(parts) == 3 and method == "GET":
                return self.send(200, service.view(research_id))
            if len(parts) == 4 and parts[3] == "actions" and method == "POST":
                body = self.body()
                service.act(research_id, body.get("revision"), body.get("action"),
                            body.get("payload", {}), body.get("actor", "owner"))
                return self.send(200, service.view(research_id))
            if len(parts) == 4 and parts[3] == "history" and method == "GET":
                return self.send(200, service.store.history(research_id))
            if len(parts) >= 4 and parts[3] == "jobs":
                jobs = self.server.jobs
                if len(parts) == 4 and method == "GET":
                    return self.send(200, jobs_overview(jobs, service, research_id))
                if jobs is None:
                    raise ValidationError(provider_status("disabled")["message"])
                if len(parts) == 4 and method == "POST":
                    body = self.body()
                    return self.send(201, jobs.enqueue(research_id, "owner", body.get("idempotency_key"),
                                                       body.get("plan_query_id"), body.get("confirm_paid") is True))
                if len(parts) == 6 and parts[5] == "cancel" and method == "POST":
                    self.body()
                    jobs.cancel(research_id, parts[4])
                    return self.send(200, jobs.overview(research_id))
            if len(parts) == 4 and parts[3] == "strategy" and method == "GET":
                return self.send(200, strategy_report.html(strategy(service.store.get(research_id)), style_href="/strategy.css"),
                                 "text/html; charset=utf-8")
            if len(parts) == 5 and parts[3] == "agent" and method == "GET":
                return self.send(200, role_task(service.store.get(research_id), parts[4]),
                                 filename=f"{research_id}-{parts[4]}.json")
            if len(parts) == 4 and parts[3] == "export" and method == "GET":
                return self.send(200, markdown(service.store.get(research_id)), "text/markdown; charset=utf-8",
                                 filename=f"{research_id}.md")
            if len(parts) == 4 and parts[3] == "export.pdf" and method == "GET":
                return self.send(200, pdf_bytes(markdown(service.store.get(research_id)), "Отчёт Sponsorship"),
                                 "application/pdf", filename=f"{research_id}.pdf")
            if len(parts) == 4 and parts[3] == "handoff" and method == "GET":
                return self.send(200, handoff_markdown(readiness(service.store.get(research_id))),
                                 "text/markdown; charset=utf-8", filename=f"{research_id}-handoff.md")
            if len(parts) == 4 and parts[3] == "handoff.pdf" and method == "GET":
                return self.send(200, pdf_bytes(handoff_markdown(readiness(service.store.get(research_id))), "Пакет для отделов"),
                                 "application/pdf", filename=f"{research_id}-handoff.pdf")
        return self.send(404, {"error": "Страница не найдена"})

    def execute(self, method):
        try:
            self.dispatch(method)
        except ConflictError as exc:
            self.send(409, {"error": str(exc)})
        except (ValidationError, ValueError) as exc:
            self.send(400, {"error": str(exc)})
        except PDFUnavailable as exc:
            self.send(503, {"error": str(exc)})
        except KeyError as exc:
            self.send(404, {"error": exc.args[0] if exc.args else "Не найдено"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send(500, {"error": "Внутренняя ошибка. Проверьте локальный журнал и входные материалы."})

    def do_GET(self):
        self.execute("GET")

    def do_POST(self):
        self.execute("POST")
