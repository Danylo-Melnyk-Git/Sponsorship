"""Background discovery search: web queue -> worker -> the same validated role import.

Search results are leads (access="search_lead"), never read evidence. The worker
never selects, approves or reads pages; people and the chat path do that.
"""
from datetime import date
import importlib.util

from packages.connectors.legacy import search_plan
from packages.domain.agents import import_result, role_task
from packages.domain.models import ConflictError, ValidationError, require

from .config import secret

SEARCH_PROVIDERS = ("disabled", "exa", "stub")
ROLE = "discovery"
PAID = {"exa"}


def provider_status(provider):
    """What the interface may offer. Never returns secret values."""
    base = {"provider": provider, "paid": provider in PAID, "synthetic_only": provider == "stub"}
    if provider == "stub":
        return base | {"available": True, "message": "Тестовый провайдер: синтетические ссылки без сетевых вызовов. "
                       "Доступен только для учебных (синтетических) исследований."}
    if provider == "exa":
        if importlib.util.find_spec("httpx") is None:
            return base | {"available": False, "message": "Поиск Exa настроен, но не установлен httpx "
                           "(python -m pip install -r requirements-server.txt). Задания не создаются."}
        try:
            secret("EXA_API_KEY")
        except (ValueError, OSError):
            return base | {"available": False, "message": "Ключ поиска не найден: задайте EXA_API_KEY_FILE с путём к файлу ключа "
                           "и перезапустите сервер и воркер. Задания не создаются; исследование можно продолжить через чат."}
        return base | {"available": True, "message": "Поиск Exa: каждое задание — один платный запрос; стоимость известна, "
                       "только если её вернул провайдер. Результаты — непрочитанные ссылки."}
    return base | {"available": False, "message": "Фоновый поиск не настроен. Администратор задаёт SPONSOR_SEARCH_PROVIDER=exa "
                   "и EXA_API_KEY_FILE (платные вызовы) или stub для проверки на учебном исследовании. "
                   "Пока исследование продолжается через контекст роли в чате."}


def _executed(state):
    return {s.get("plan_query_id") for s in state["search_log"]
            if s.get("plan_query_id") and s.get("brief_version") == state["brief_version"]
            and s["status"] in ("completed", "failed")}


def plan_options(state, jobs):
    """Scheduled plan queries that are neither executed nor reserved by the queue."""
    plan = search_plan(state)
    reserved = {j.get("plan_query_id") for j in jobs.active_inputs(state["id"], "search")
                if j.get("brief_version") == state["brief_version"]}
    done = _executed(state)
    return [{"id": q["id"], "query": q["arguments"]["query"], "geo": q["geo"], "language": q["language"],
             "category": q["category"], "lane": q["lane"],
             "status": "done" if q["id"] in done else "queued" if q["id"] in reserved else "open"}
            for q in plan["scheduled"]], plan


class ResearchJobs:
    def __init__(self, store, service, provider="disabled", daily_limit=20):
        require(provider in SEARCH_PROVIDERS, "Неизвестный поисковый провайдер")
        self.store, self.service, self.provider, self.daily_limit = store, service, provider, daily_limit

    def status(self):
        return provider_status(self.provider)

    def overview(self, research_id):
        state = self.service.store.get(research_id)
        status = self.status()
        result = {"provider": status, "jobs": self.store.list(research_id), "queries": [], "can_enqueue": False, "blocked": None}
        try:
            role_task(state, ROLE)
            options, _ = plan_options(state, self.store)
            result["queries"] = options
        except ValidationError as exc:
            result["blocked"] = str(exc)
            return result
        if state["case"] is not None:
            result["blocked"] = "Кейс завершён"
        elif status["synthetic_only"] and state["kind"] != "synthetic":
            result["blocked"] = "Тестовый провайдер доступен только для учебного исследования"
        elif not status["available"]:
            result["blocked"] = status["message"]
        elif not any(q["status"] == "open" for q in result["queries"]):
            result["blocked"] = "Все запросы текущего плана выполнены или стоят в очереди; измените бриф или лимит поиска"
        result["can_enqueue"] = result["blocked"] is None
        return result

    def enqueue(self, research_id, username, idempotency_key, plan_query_id=None, confirm_paid=False):
        status = self.status()
        require(status["available"], status["message"])
        state = self.service.store.get(research_id)
        require(state["case"] is None, "Кейс завершён")
        role_task(state, ROLE)  # same stage gate as the chat import
        require(not status["synthetic_only"] or state["kind"] == "synthetic",
                "Тестовый провайдер доступен только для учебного исследования")
        require(not status["paid"] or confirm_paid is True, "Подтвердите платный запрос к провайдеру поиска")
        options, plan = plan_options(state, self.store)
        open_ids = [q for q in options if q["status"] == "open"]
        if plan_query_id:
            chosen = next((q for q in options if q["id"] == plan_query_id), None)
            require(chosen is not None, "Запрос не относится к текущему плану")
            require(chosen["status"] == "open", "Этот запрос уже выполнен или стоит в очереди")
        else:
            require(open_ids, "Все запросы текущего плана выполнены или стоят в очереди")
            chosen = open_ids[0]
        used = sum(s["status"] in ("completed", "failed") for s in state["search_log"])
        payload = {"query": chosen["query"], "plan_query_id": chosen["id"], "brief_version": state["brief_version"],
                   "num_results": max(1, min(10, int(plan["settings"].get("num_results", 5)))),
                   "provider": self.provider, "role": ROLE}
        return self.store.create(username, idempotency_key, state, "search", payload, self.daily_limit,
                                 used, state["brief"]["max_search_calls"])

    def cancel(self, research_id, job_id):
        self.store.cancel(job_id, research_id)


class StubSearch:
    """Deterministic offline provider for tests and synthetic walkthroughs."""

    def run(self, job):
        data = job["input"]
        return {"status": "leads_require_reading", "provider": "stub", "retrieved_at": date.today().isoformat(),
                "query": data["query"], "plan_query_id": data["plan_query_id"], "brief_version": data["brief_version"],
                "results": [{"title": f"Синтетическая ссылка {n} · {data['plan_query_id']}",
                             "url": f"https://example.org/stub/{data['plan_query_id']}/{n}",
                             "publishedDate": None, "author": None} for n in range(1, min(3, data.get("num_results", 3)) + 1)],
                "request_id": None, "reported_cost": None,
                "note": "Синтетическая выдача тестового провайдера; сетевых вызовов не было."}


def _cost(reported):
    if isinstance(reported, (int, float)) and not isinstance(reported, bool):
        return float(reported)
    if isinstance(reported, dict) and isinstance(reported.get("total"), (int, float)):
        return float(reported["total"])
    return None


def operations(job, output):
    synthetic = output["provider"] == "stub"
    retrieved = str(output.get("retrieved_at", ""))[:10] or date.today().isoformat()
    ops, ids = [], []
    for n, row in enumerate(output.get("results", []), 1):
        url = row.get("url")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            continue
        title = str(row.get("title") or url)[:500]
        published = row.get("publishedDate")
        published = published[:10] if isinstance(published, str) and len(published) >= 10 else None
        if published:
            try:
                published = min(date.fromisoformat(published), date.today()).isoformat()
            except ValueError:
                published = None
        source_id = f"src-{job['id'][4:16]}-{n}"
        ids.append(source_id)
        ops.append({"action": "add_source", "payload": {
            "id": source_id, "title": title, "url": url, "kind": "synthetic" if synthetic else "public",
            "access": "search_lead", "retrieved_on": retrieved, "published_on": published,
            "excerpt": "Поисковая выдача, страница не прочитана: " + title
                       + (f". Автор: {row['author']}" if row.get("author") else ""),
            "search_provider": output["provider"], "job_id": job["id"]}})
    cost = _cost(output.get("reported_cost"))
    ops.append({"action": "record_search", "payload": {
        "id": "search-" + job["id"], "query": job["input"]["query"], "provider": output["provider"],
        "status": "completed", "pages_read": 0, "plan_query_id": job["input"]["plan_query_id"],
        "cost": cost, "cost_currency": "USD" if cost is not None else None, "read_attempts": [],
        "result_source_ids": ids, "job_id": job["id"], "request_id": output.get("request_id"),
        "note": "Фоновое задание: найдены ссылки, страницы не прочитаны. "
                + ("Стоимость сообщена провайдером." if cost is not None else "Стоимость неизвестна.")}})
    return ops


def _import(service, job, ops):
    """Re-read the research before each attempt; every operation is re-validated on the current state."""
    for _ in range(3):
        state = service.store.get(job["research_id"])
        require(state["brief_version"] == job["input"]["brief_version"],
                "Бриф изменился после постановки задания; ссылки оставлены в задании для ручной проверки")
        try:
            return import_result(service, {"research_id": state["id"], "expected_revision": state["revision"],
                                           "role": job["input"].get("role", ROLE), "operations": ops})
        except ConflictError:
            continue
    raise ValidationError("Исследование одновременно изменялось; импорт не выполнен, ссылки оставлены в задании")


def process_once(store, service, runners=None):
    """Claim one job, call its provider once (no auto-retry), import via the role contract."""
    job = store.claim()
    if job is None:
        return False
    if job["kind"] != "search":
        from .providers import Providers
        try:
            store.finish(job["id"], "completed", (runners or {}).get("draft", Providers()).run(job))
        except Exception:
            store.finish(job["id"], "failed", {"error": "Внешний запрос не завершён; возможное списание неизвестно. Автоповтор отключён."})
        return True
    provider = job["input"].get("provider", "exa")
    runners = runners or {}
    try:
        if provider == "stub":
            runner = runners.get("stub") or StubSearch()
        else:
            from .providers import Providers
            runner = runners.get(provider) or Providers()
        output = runner.run(job)
    except Exception:
        # Provider bodies and exception text can contain secrets or inputs.
        failure = {"error": "Внешний запрос не завершён. Проверьте конфигурацию и кабинет провайдера; "
                            "возможное списание неизвестно. Автоповтор отключён."}
        try:
            _import(service, job, [{"action": "record_search", "payload": {
                "id": "search-" + job["id"], "query": job["input"]["query"], "provider": provider, "status": "failed",
                "pages_read": 0, "plan_query_id": job["input"]["plan_query_id"], "cost": None, "read_attempts": [],
                "job_id": job["id"], "note": "Фоновый вызов не завершён; возможное списание неизвестно."}}])
            failure["search_log"] = "recorded"
        except (ValidationError, KeyError, ValueError):
            failure["search_log"] = "not_recorded"
        store.finish(job["id"], "failed", failure)
        return True
    ops = operations(job, output)
    try:
        state = _import(service, job, ops)
        output["import"] = {"status": "imported", "revision": state["revision"],
                            "sources": sum(op["action"] == "add_source" for op in ops)}
        store.finish(job["id"], "completed", output)
    except (ValidationError, KeyError, ValueError) as exc:
        output["import"] = {"status": "rejected", "reason": str(exc)}
        store.finish(job["id"], "import_rejected", output)
    return True
