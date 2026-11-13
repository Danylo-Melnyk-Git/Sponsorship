"""Six-stage application service. Every write is versioned and transactional."""

from copy import deepcopy
from datetime import date, timedelta
import re

from .models import (
    CRITERIA, GOALS, METRICS, STAGES, TASK_STATUSES, ValidationError, brief_missing,
    identifier, integer, iso_date, number, refs, require, text, today, utcnow,
    validate_brief, validate_candidate, validate_package, validate_source, validate_weights,
)
from packages.scoring.engine import MODEL_VERSION, PROFILES, comparison, evaluate
from packages.scoring.weights import DEFAULT_PROFILE
from .quality import save_measurement, record_assessment, readiness
from .activation import (save_pool, save_entry, review_register, waive_entry, validate_task_links,
                         task_blockers, acknowledge_task, activation_review, catalog)


def find(items, item_id, label):
    for item in items:
        if item["id"] == item_id:
            return item
    raise ValidationError(f"{label} не найден")


def usable_refs(ids, state, required=True):
    refs(ids, state["sources"], required=required)
    by_id = {s["id"]: s for s in state["sources"]}
    require(all(by_id[sid]["access"] in ("page_read", "provided_material") for sid in ids),
            "Поисковый сниппет нельзя использовать как доказательство")


def decision_current(state, decision, package):
    return (decision.get("brief_version") == state["brief_version"]
            and decision.get("weights_version") == state["weights_version"]
            and decision.get("package_version") == package.get("package_version", 1))


class ResearchService:
    def __init__(self, store):
        self.store = store

    def create(self, payload):
        require(isinstance(payload, dict), "Запрос должен быть объектом")
        title = text(payload.get("title"), "Название исследования", limit=300)
        kind = payload.get("kind", "owner_brief")
        require(kind in ("owner_brief", "synthetic"), "Неизвестный тип исследования")
        brief = validate_brief(payload.get("brief", {}))
        profile = brief["goal"] or DEFAULT_PROFILE
        return self.store.create({
            "schema_version": "1.0", "title": title, "kind": kind,
            "request": text(payload.get("request", ""), "Исходный запрос", required=False),
            "stage": "brief", "brief_version": 1, "brief": brief, "profile": profile,
            "weights": deepcopy(PROFILES[profile]), "weights_version": 1,
            "sources": [], "candidates": [], "packages": [], "offers": [], "decisions": [],
            "tasks": [], "outcomes": [], "search_log": [], "campaign": None, "case": None,
            "measurement_plans": [], "assessments": [], "register": [], "pool_reviews": [], "register_reviews": [],
        })

    def act(self, research_id, revision, action, payload, actor="owner"):
        integer(revision, "Версия", low=1)
        require(isinstance(payload, dict), "Данные действия должны быть объектом")
        actor = text(actor, "Автор действия", limit=200)
        if actor.startswith("agent:"):
            require(action in ("batch", "add_source", "save_candidate", "save_package", "record_search"),
                    "Роль не может выполнять ручной выбор, утверждение или приёмку")
        methods = {
            "update_brief": self._update_brief, "add_source": self._add_source,
            "save_candidate": self._save_candidate, "select_candidate": self._select_candidate,
            "save_package": self._save_package, "set_weights": self._set_weights,
            "record_search": self._record_search, "decision": self._decision,
            "receive_offer": self._receive_offer, "advance": self._advance,
            "start_campaign": self._start_campaign, "save_task": self._save_task,
            "task_status": self._task_status, "record_outcome": self._record_outcome,
            "close_case": self._close_case, "batch": self._batch,
            "save_measurement": save_measurement, "record_assessment": record_assessment,
            "save_pool": save_pool, "save_entry": save_entry, "review_register": review_register,
            "waive_entry": waive_entry, "acknowledge_task": acknowledge_task,
            "template_task": self._template_task,
        }
        require(action in methods, "Неизвестное действие")

        def mutate(state):
            require(state["case"] is None, "Кейс завершён и сохранён. Создайте новое исследование для продолжения.")
            methods[action](state, payload, actor)

        return self.store.update(research_id, revision, action, actor, payload, mutate)

    def create_signed(self, payload):
        """Import an already signed partnership without invented research/approvals."""
        require(isinstance(payload, dict), "Карточка партнёрства должна быть объектом")
        kind = payload.get("kind", "owner_brief")
        require(kind in ("owner_brief", "synthetic"), "Неизвестный тип карточки")
        brief = validate_brief(payload.get("brief", {}))
        sources = payload.get("sources", [])
        require(isinstance(sources, list) and sources, "Добавьте материал подписанного партнёрства")
        sources = [validate_source(s, kind == "synthetic") for s in sources]
        require(len({s["id"] for s in sources}) == len(sources), "Повторный ID источника")
        agreement = payload.get("agreement")
        require(isinstance(agreement, dict), "Добавьте сведения о партнёрстве")
        start = iso_date(agreement.get("start"), "Начало партнёрства")
        end = iso_date(agreement.get("end"), "Окончание партнёрства")
        require(start <= end, "Период партнёрства перепутан")
        currency = text(agreement.get("currency"), "Валюта учёта")
        require(re.fullmatch(r"[A-Z]{3}", currency), "Валюта: три заглавные буквы")
        note = text(agreement.get("note"), "Сведения о подписанных обязательствах")
        partner = text(agreement.get("partner"), "Партнёр")
        provisional = {"sources": sources}
        usable_refs(agreement.get("source_ids", []), provisional)
        campaign = {"id": identifier("campaign"), "origin": "signed_import", "partner": partner,
                    "offer_id": None, "start": start, "end": end, "agreement_note": note,
                    "source_ids": deepcopy(agreement["source_ids"]), "started_at": utcnow(), "started_by": "owner",
                    "measurement_baseline": None,
                    "baseline": {"brief": deepcopy(brief), "brief_version": 1, "candidate": None, "weights": None,
                                 "model_version": None, "evaluation": None,
                                 "package": {"name": "Подписанное партнёрство", "deliverables": note, "rights": "",
                                             "forecast": None, "fee": {"status": "unknown", "currency": currency}}}}
        return self.store.create({
            "schema_version": "1.0", "title": text(payload.get("title"), "Название", limit=300), "kind": kind,
            "request": text(payload.get("request", ""), "Исходный запрос", required=False), "entry_mode": "signed_import",
            "stage": "deliver", "brief_version": 1, "brief": brief, "profile": brief["goal"] or DEFAULT_PROFILE,
            "weights": deepcopy(PROFILES[brief["goal"] or DEFAULT_PROFILE]), "weights_version": 1,
            "sources": sources, "candidates": [], "packages": [], "offers": [], "decisions": [], "tasks": [],
            "outcomes": [], "search_log": [], "campaign": campaign, "case": None, "measurement_plans": [],
            "assessments": [], "register": [], "pool_reviews": [], "register_reviews": []})

    def _batch(self, state, payload, actor):
        operations = payload.get("operations")
        require(isinstance(operations, list) and 0 < len(operations) <= 100, "Пакет: от 1 до 100 операций")
        allowed = {"add_source": self._add_source, "save_candidate": self._save_candidate,
                   "save_package": self._save_package, "record_search": self._record_search}
        for operation in operations:
            require(isinstance(operation, dict) and operation.get("action") in allowed,
                    "В пакетном импорте разрешены источники, кандидаты, пакеты и журнал поиска")
            require(isinstance(operation.get("payload"), dict), "Неверная операция импорта")
            allowed[operation["action"]](state, operation["payload"], actor)

    def _update_brief(self, state, payload, actor):
        brief = validate_brief(payload.get("brief", {}))
        require(brief != state["brief"], "Бриф не изменился")
        state["brief"] = brief
        state["brief_version"] += 1
        if payload.get("reset_weights"):
            state["profile"] = brief["goal"] or DEFAULT_PROFILE
            state["weights"] = deepcopy(PROFILES[state["profile"]])
            state["weights_version"] += 1
        if state["stage"] in ("brief", "screen", "deep", "negotiate"):
            state["stage"] = "brief"

    def _add_source(self, state, payload, actor):
        item = validate_source(payload, state["kind"] == "synthetic")
        existing = next((s for s in state["sources"] if s["id"] == item["id"]), None)
        if existing is not None:
            require(existing == item, "Источник с этим ID уже существует; добавьте новое наблюдение с новым ID")
            return
        state["sources"].append(item)

    def _save_candidate(self, state, payload, actor):
        item = validate_candidate(payload, state["sources"])
        previous = next((c for c in state["candidates"] if c["id"] == item["id"]), None)
        if actor.startswith("agent:"):
            previous_risk = previous["risk"] if previous else None
            unchanged = previous_risk == item["risk"]
            require(unchanged or (item["risk"]["status"] in ("not_checked", "flagged")
                                  and not item["risk"].get("human_reviewed")
                                  and (not previous_risk or previous_risk["status"] != "confirmed_block")),
                    "Роль передаёт проверку и снятие критического риска человеку")
        for candidate in state["candidates"]:
            require(candidate["id"] == item["id"] or candidate["entity_key"] != item["entity_key"],
                    "Эта идентичность уже есть. Дополните существующего кандидата.")
        item["selected"] = previous["selected"] if previous else False
        item["selection_reason"] = previous.get("selection_reason", "") if previous else ""
        for metric in item["metrics"]:
            if metric.get("followers") is not None:
                usable_refs(metric["evidence_ids"], state)
        if item["risk"]["status"] in ("flagged", "confirmed_block"):
            usable_refs(item["risk"]["source_ids"], state)
        if previous:
            state["candidates"][state["candidates"].index(previous)] = item
        else:
            state["candidates"].append(item)

    def _select_candidate(self, state, payload, actor):
        require(state["stage"] in ("screen", "deep"), "Ручной выбор выполняется на этапе отбора/анализа")
        candidate = find(state["candidates"], payload.get("candidate_id"), "Кандидат")
        require(isinstance(payload.get("selected"), bool), "Нужен явный выбор")
        reason = text(payload.get("reason"), "Основание ручного выбора")
        if payload["selected"]:
            require(candidate["queue"] != "excluded" and candidate["risk"]["status"] != "confirmed_block",
                    "Кандидат исключён; сначала пересмотрите основание исключения")
        candidate["selected"] = payload["selected"]
        candidate["selection_reason"] = reason
        candidate["selected_by"] = actor
        candidate["selected_on"] = utcnow()

    def _save_package(self, state, payload, actor):
        require(state["stage"] in ("deep", "negotiate"), "Пакеты редактируются при глубоком анализе/проработке условий")
        candidate = find(state["candidates"], payload.get("candidate_id"), "Кандидат")
        require(candidate["selected"], "Сначала выберите кандидата для глубокого анализа")
        previous = next((p for p in state["packages"] if p["id"] == payload.get("id")), None)
        if previous and previous["brief_version"] != state["brief_version"]:
            require(payload.get("reassess") is True, "Оценки устарели; подтвердите пересмотр под новый бриф")
            text(payload.get("reassessment_reason"), "Основание повторной оценки")
        item = validate_package(payload, state)
        received = next((o for o in state["offers"] if o["package_id"] == item["id"]), None)
        if received:
            require(all(item["fee"].get(k) == received["fee"].get(k)
                        for k in ("status", "low", "high", "currency", "valid_on", "basis")),
                    "Полученную цену меняйте новым предложением; прежний ответ сохраняется")
        item["package_version"] = previous.get("package_version", 1) + 1 if previous else 1
        for entry in item["criteria"].values():
            if entry["value"] is not None:
                usable_refs(entry["source_ids"], state)
        if item["fee"]["status"] != "unknown":
            usable_refs(item["fee"]["source_ids"], state)
        if item["forecast"] is not None:
            usable_refs(item["forecast"]["source_ids"], state)
        if previous:
            state["packages"][state["packages"].index(previous)] = item
        else:
            state["packages"].append(item)

    def _set_weights(self, state, payload, actor):
        text(payload.get("reason"), "Почему изменены веса")
        state["weights"] = validate_weights(payload.get("weights"))
        state["weights_version"] += 1
        state["profile"] = "custom"

    def _record_search(self, state, payload, actor):
        item = deepcopy(payload)
        item["id"] = item.get("id") or identifier("search")
        text(item.get("query"), "Запрос поиска")
        text(item.get("provider"), "Инструмент")
        require(item.get("status") in ("completed", "failed", "deferred"), "Неверный статус поиска")
        integer(item.get("pages_read", 0), "Количество прочитанных страниц")
        number(item.get("cost"), "Расход", optional=True)
        if item.get("plan_query_id"):
            from packages.connectors.legacy import search_plan
            queries = {q["id"] for q in search_plan(state)["scheduled"]}
            require(item["plan_query_id"] in queries, "Запрос не относится к текущему плану")
        reads = item.setdefault("read_attempts", [])
        require(isinstance(reads, list) and all(isinstance(r, dict) for r in reads), "Неверные попытки чтения")
        for attempt in reads:
            text(attempt.get("reference"), "URL/материал попытки чтения")
            require(attempt.get("status") in ("read", "blocked", "failed"), "Неверный результат попытки чтения")
            iso_date(attempt.get("on"), "Дата попытки", future=False)
            refs(attempt.get("source_ids", []), state["sources"])
        if reads:
            require(item.get("pages_read", 0) == sum(r["status"] == "read" for r in reads), "Число прочитанных страниц отличается от журнала попыток")
        item.setdefault("cost", None)
        item.setdefault("cost_currency", None)
        if item["cost"] is not None:
            text(item.get("cost_currency"), "Валюта расходов")
        item["recorded_at"] = utcnow()
        item["brief_version"] = state["brief_version"]
        require(not any(s["id"] == item["id"] for s in state["search_log"]), "Запрос уже записан в журнал")
        completed = sum(s["status"] in ("completed", "failed") for s in state["search_log"])
        pages = sum(s.get("pages_read", 0) for s in state["search_log"])
        require(item["status"] == "deferred" or completed < state["brief"]["max_search_calls"],
                "Лимит поисковых вызовов исчерпан; измените бриф для расширения")
        require(pages + item.get("pages_read", 0) <= state["brief"]["max_pages"],
                "Лимит прочитанных страниц исчерпан")
        state["search_log"].append(item)

    def _decision(self, state, payload, actor):
        decision = deepcopy(payload)
        require(decision.get("kind") in ("c_level_continue", "approve_offer", "decline_offer"),
                "Неизвестный тип решения")
        text(decision.get("reason"), "Основание решения")
        text(decision.get("decision_maker"), "Кто принял решение")
        if decision["kind"] == "c_level_continue":
            package = find(state["packages"], decision.get("package_id"), "Пакет")
            candidate = find(state["candidates"], package["candidate_id"], "Кандидат")
            require(candidate["selected"] and candidate["risk"]["status"] != "confirmed_block",
                    "Кандидат не выбран или исключён")
            require(package["brief_version"] == state["brief_version"], "Сначала пересмотрите пакет под текущий бриф")
        else:
            offer = find(state["offers"], decision.get("offer_id"), "Предложение")
            package = find(state["packages"], offer["package_id"], "Пакет предложения")
            if decision["kind"] == "approve_offer":
                candidate = find(state["candidates"], package["candidate_id"], "Кандидат")
                require(candidate["risk"]["status"] == "reviewed" and candidate["queue"] != "excluded",
                        "До утверждения предложения требуется разрешить риск")
                require(package["brief_version"] == state["brief_version"], "Предложение относится к прежнему брифу")
                require(offer["fee"]["status"] != "unknown", "Для сделки требуется реальная цена")
        decision.update(id=identifier("decision"), brief_version=state["brief_version"],
                        weights_version=state["weights_version"], package_version=package.get("package_version", 1),
                        actor=actor, at=utcnow())
        state["decisions"].append(decision)

    def _receive_offer(self, state, payload, actor):
        require(state["stage"] == "negotiate", "Реальные условия вводятся на этапе проработки")
        original = find(state["packages"], payload.get("package_id"), "Пакет")
        continuation = [d for d in state["decisions"] if d["kind"] == "c_level_continue"
                        and d.get("package_id") == original["id"] and decision_current(state, d, original)]
        require(continuation, "Зафиксируйте разрешение C-level на проработку этого пакета")
        usable_refs(payload.get("source_ids", []), state)
        text(payload.get("representative"), "Представитель / источник условий")
        text(payload.get("note"), "Содержание ответа")
        proposed = deepcopy(original)
        proposed["id"] = identifier("pkg")
        proposed["name"] = original["name"] + " · полученные условия"
        proposed["supersedes"] = original["id"]
        proposed["package_version"] = 1
        proposed["fee"] = deepcopy(payload.get("fee", {}))
        proposed["fee"]["source_ids"] = payload["source_ids"]
        proposed["fee"]["basis"] = "this_package"
        for key in ("months", "territory", "deliverables", "rights", "extra_costs"):
            if key in payload:
                proposed[key] = deepcopy(payload[key])
        terms_changed = any(proposed[k] != original[k] for k in ("months", "territory", "deliverables", "rights"))
        if terms_changed:
            proposed["criteria"] = {key: {"value": None, "reason": "Условия изменились: требуется оценка",
                                                "source_ids": []} for key in CRITERIA}
            proposed["forecast"] = None
        proposed = validate_package(proposed, state)
        require(proposed["fee"]["status"] in ("reported", "published"), "Ответ менеджера должен содержать полученную цену")
        state["packages"].append(proposed)
        state["offers"].append({
            "id": identifier("offer"), "package_id": proposed["id"], "original_package_id": original["id"],
            "representative": payload["representative"], "note": payload["note"], "source_ids": payload["source_ids"],
            "fee": deepcopy(proposed["fee"]), "brief_version": state["brief_version"], "at": utcnow(),
        })

    def _advance(self, state, payload, actor):
        index = STAGES.index(state["stage"])
        require(index < len(STAGES) - 1, "Это последний этап")
        if state["stage"] == "brief":
            missing = brief_missing(state["brief"])
            require(not missing, "Уточните бриф: " + ", ".join(missing))
        elif state["stage"] == "screen":
            require(any(c["selected"] for c in state["candidates"]), "Выберите пул для глубокого анализа")
        elif state["stage"] == "deep":
            require(any(d["kind"] == "c_level_continue" and p["id"] == d.get("package_id")
                        and decision_current(state, d, p) for d in state["decisions"] for p in state["packages"]),
                    "Зафиксируйте разрешение C-level на текущую версию пакета и приоритетов")
        elif state["stage"] == "negotiate":
            raise ValidationError("Начните кампанию по утверждённому предложению")
        elif state["stage"] == "deliver":
            require(state["campaign"] is not None, "Кампания не начата")
        state["stage"] = STAGES[index + 1]

    def _start_campaign(self, state, payload, actor):
        require(state["stage"] == "negotiate" and state["campaign"] is None, "Кампания уже начата или этап не подходит")
        offer = find(state["offers"], payload.get("offer_id"), "Предложение")
        decisions = [d for d in state["decisions"] if d["kind"] in ("approve_offer", "decline_offer")
                     and d.get("offer_id") == offer["id"] and d["brief_version"] == state["brief_version"]]
        require(decisions and decisions[-1]["kind"] == "approve_offer", "Предложение не утверждено")
        usable_refs(payload.get("source_ids", []), state)
        text(payload.get("agreement_note"), "Подтверждение согласованных обязательств")
        package = find(state["packages"], offer["package_id"], "Пакет")
        require(decision_current(state, decisions[-1], package),
                "Пакет или приоритеты изменились после утверждения; требуется новое решение")
        candidate = find(state["candidates"], package["candidate_id"], "Кандидат")
        require(package["brief_version"] == state["brief_version"], "Пересмотрите условия под текущий бриф")
        require(candidate["risk"]["status"] == "reviewed" and candidate["selected"]
                and candidate["queue"] != "excluded", "Кандидат требует повторной модерации")
        start = iso_date(payload.get("start"), "Начало кампании")
        end = iso_date(payload.get("end"), "Конец кампании")
        require(start <= end, "Конец кампании раньше начала")
        state["campaign"] = {
            "id": identifier("campaign"), "offer_id": offer["id"], "start": start, "end": end,
            "agreement_note": payload["agreement_note"], "source_ids": payload["source_ids"],
            "started_at": utcnow(), "started_by": actor,
            "baseline": {"brief": deepcopy(state["brief"]), "brief_version": state["brief_version"],
                         "package": deepcopy(package), "candidate": deepcopy(candidate),
                         "weights": deepcopy(state["weights"]), "model_version": MODEL_VERSION,
                         "evaluation": evaluate(package, candidate, state)},
            "measurement_baseline": deepcopy(readiness(state)["measurement"]["plan"]),
        }
        state["stage"] = "deliver"

    def _save_task(self, state, payload, actor):
        require(state["campaign"] is not None and state["stage"] in ("deliver", "report"), "Сначала начните кампанию")
        previous = next((t for t in state["tasks"] if t["id"] == payload.get("id")), None)
        item = {**deepcopy(previous or {}), **deepcopy(payload)}
        item["id"] = item.get("id") or identifier("task")
        for key, label in (("title", "Задача"), ("owner", "Ответственный")):
            item[key] = text(item.get(key), label)
        item["due"] = iso_date(item.get("due"), "Срок")
        item["next_action"] = text(item.get("next_action", ""), "Следующий шаг", required=False)
        item["status"] = previous["status"] if previous else "planned"
        item["source_ids"] = previous.get("source_ids", []) if previous else []
        item.pop("acknowledgement", None)
        item["version"] = previous.get("version", 1) + 1 if previous else 1
        validate_task_links(state, item)
        if previous:
            require(previous["status"] not in ("accepted", "waived"), "Принятая задача сохраняется в истории")
            state["tasks"][state["tasks"].index(previous)] = item
        else:
            state["tasks"].append(item)

    def _template_task(self, state, payload, actor):
        pool = next((p for p in catalog() if any(t["id"] == payload.get("template_id") for t in p["templates"])), None)
        require(pool is not None, "Шаблон задачи не найден")
        reviews = [r for r in state.get("pool_reviews", []) if r["pool_id"] == pool["id"]]
        require(reviews and reviews[-1]["status"] == "applies", "Сначала подтвердите применимость пула")
        template = next(t for t in pool["templates"] if t["id"] == payload["template_id"])
        self._save_task(state, {**payload, "title": template["title"], "acceptance": template["acceptance"],
                               "pool_id": pool["id"], "requires_ack": True}, actor)

    def _task_status(self, state, payload, actor):
        task = find(state["tasks"], payload.get("task_id"), "Задача")
        require(payload.get("status") in TASK_STATUSES, "Неизвестный статус задачи")
        require(task["status"] not in ("accepted", "waived"), "Принятое обязательство уже зафиксировано")
        if payload["status"] in ("in_progress", "submitted", "accepted"):
            require(not task_blockers(state, task), "Сначала разрешите зависимости и подтвердите назначение")
        if payload["status"] in ("submitted", "accepted"):
            usable_refs(payload.get("source_ids", []), state)
        if payload["status"] in ("blocked", "waived"):
            text(payload.get("reason"), "Причина изменения обязательства")
        task.update(status=payload["status"], source_ids=payload.get("source_ids", []),
                    status_reason=payload.get("reason", ""), updated_by=actor, updated_at=utcnow())

    def _record_outcome(self, state, payload, actor):
        require(state["campaign"] is not None and state["stage"] in ("deliver", "report"), "Нет начатой кампании")
        item = deepcopy(payload)
        require(item.get("metric") in (*METRICS, "full_cost"), "Неизвестная метрика результата")
        number(item.get("value"), "Фактический результат", high=100 if item["metric"].endswith("_rate") else None)
        usable_refs(item.get("source_ids", []), state)
        start = iso_date(item.get("start"), "Начало периода")
        end = iso_date(item.get("end"), "Конец периода", future=False)
        require(start <= end, "Неверный период результата")
        require(item.get("scope") in ("campaign_total", "partial"), "Укажите полный или частичный результат")
        if item["metric"] == "full_cost":
            require(item.get("currency") == state["campaign"]["baseline"]["package"]["fee"]["currency"],
                    "Валюта фактических затрат отличается от валюты пакета")
        if item["metric"] == "unique_reach":
            text(item.get("deduplication"), "Метод уникального охвата")
        item.update(id=identifier("outcome"), at=utcnow(), recorded_by=actor)
        state["outcomes"].append(item)

    def _close_case(self, state, payload, actor):
        require(state["stage"] == "report" and state["campaign"] is not None, "Завершение выполняется в результатах")
        require(state["tasks"] and all(t["status"] in ("accepted", "waived") for t in state["tasks"]),
                "Завершите приёмку или явно снимите открытые обязательства")
        if state.get("register"):
            review = activation_review(state)
            require(review["register_review_current"], "Полнота текущего реестра не сверена с договором")
            require(all(e.get("waiver") or (e["quantity"] is not None and abs(e["accepted_quantity"] - e["quantity"]) < 1e-8)
                        for e in review["register"]), "Есть неисполненные обязательства или права без решения об остатке")
        require(payload.get("recommendation") in ("renew", "change", "stop"), "Выберите итоговое решение")
        text(payload.get("lessons"), "Выводы для следующих кампаний")
        state["case"] = {**deepcopy(payload), "at": utcnow(), "actor": actor}

    def view(self, research_id):
        state = self.store.get(research_id)
        return {**state, "missing_brief": brief_missing(state["brief"]),
                "comparison": comparison(state), "weekly": weekly(state), "report": campaign_report(state),
                "readiness": readiness(state)}


def weekly(state, as_of=None):
    current = as_of or today()
    open_tasks = [t for t in state["tasks"] if t["status"] not in ("accepted", "waived")]
    return {
        "as_of": current.isoformat(),
        "overdue": [t for t in open_tasks if date.fromisoformat(t["due"]) < current],
        "next_seven_days": [t for t in open_tasks if current <= date.fromisoformat(t["due"]) <= current + timedelta(days=7)],
        "awaiting_acceptance": [t for t in open_tasks if t["status"] == "submitted"],
        "blocked": [t for t in open_tasks if t["status"] == "blocked"],
    }


def campaign_report(state):
    campaign = state["campaign"]
    if campaign is None:
        return {"status": "not_started", "metrics": [], "actual_full_cost": None,
                "roi": {"status": "insufficient_data", "value": None}}
    baseline = campaign["baseline"]
    forecast = baseline["package"].get("forecast")
    latest = {}
    partial = []
    for result in state["outcomes"]:
        if result["scope"] == "campaign_total" and result["start"] == campaign["start"] and result["end"] == campaign["end"]:
            latest[result["metric"]] = result
        else:
            partial.append(result)
    rows = []
    if forecast:
        actual = latest.get(forecast["metric"])
        rows.append({
            "metric": forecast["metric"], "forecast": deepcopy(forecast), "actual": actual,
            "delta": actual["value"] - forecast["base"] if actual else None,
            "absolute_error": abs(actual["value"] - forecast["base"]) if actual else None,
            "absolute_percentage_error": (abs(actual["value"] - forecast["base"]) / actual["value"] * 100)
            if actual and actual["value"] > 0 else None,
        })
    for key, result in latest.items():
        if key != "full_cost" and (not forecast or key != forecast["metric"]):
            rows.append({"metric": key, "forecast": None, "actual": result, "delta": None})
    return {
        "status": "closed" if state["case"] else "interim",
        "metrics": rows, "actual_full_cost": latest.get("full_cost"), "partial_observations": partial,
        "roi": {"status": "insufficient_data", "value": None,
                "reason": "Для финансового ROI нужны добавочная маржа, полные затраты и проверенный способ сравнения"},
        "baseline_model": baseline["model_version"], "baseline_brief_version": baseline["brief_version"],
    }
