"""Validation shared by the CLI, HTTP API and research roles."""

from copy import deepcopy
from datetime import date, datetime, timezone
import math
import re
from urllib.parse import urlparse
from uuid import uuid4


class ValidationError(ValueError):
    pass


class ConflictError(ValidationError):
    pass


STAGES = ("brief", "screen", "deep", "negotiate", "deliver", "report")
STAGE_LABELS = ("Бриф", "Первичный отбор", "Глубокий анализ", "Условия", "Исполнение", "Результаты")
CRITERIA = {
    "audience": "Совпадение целевой аудитории",
    "delivery": "Плановая доставка контактов",
    "fit": "Механика и соответствие бренду",
    "rights": "Права, исполнение и измеримость",
}
GOALS = {"awareness": "Узнаваемость", "trust": "Отношение и доверие", "action": "Измеримое действие"}
KINDS = ("influencer", "streamer", "athlete", "expert", "musician", "actor", "team", "club",
         "league", "federation", "tournament", "event", "race", "podcast", "media", "esports")
RISK_STATUSES = ("not_checked", "reviewed", "flagged", "confirmed_block")
TASK_STATUSES = ("planned", "in_progress", "blocked", "submitted", "accepted", "waived")
METRICS = ("qualified_impressions", "branded_impressions", "unique_reach", "clicks", "registrations",
           "brand_recall_rate", "brand_association_rate", "brand_trust_rate")


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def today():
    return date.today()


def identifier(prefix):
    return f"{prefix}-{uuid4().hex[:12]}"


def number(value, label, low=0, high=None, optional=False):
    if optional and value is None:
        return None
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), f"{label}: требуется конечное число")
    require(value >= low and (high is None or value <= high), f"{label}: недопустимый диапазон")
    return value


def integer(value, label, low=0, optional=False):
    if optional and value is None:
        return None
    number(value, label, low)
    require(isinstance(value, int), f"{label}: требуется целое число")
    return value


def text(value, label, required=True, limit=12000):
    if value is None and not required:
        return ""
    require(isinstance(value, str) and len(value) <= limit, f"{label}: неверный текст")
    value = value.strip()
    require(bool(value) or not required, f"{label}: заполните поле")
    return value


def iso_date(value, label, optional=False, future=True):
    if optional and not value:
        return None
    require(isinstance(value, str), f"{label}: требуется дата YYYY-MM-DD")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{label}: неверная дата") from exc
    require(future or result <= today(), f"{label}: дата наблюдения в будущем")
    return result.isoformat()


def refs(value, sources, required=False):
    require(isinstance(value, list) and all(isinstance(v, str) for v in value),
            "Источники должны быть списком ID")
    require(len(value) == len(set(value)), "Источник указан дважды")
    known = {s["id"] for s in sources}
    require(set(value) <= known, "Указан неизвестный источник")
    require(bool(value) or not required, "Добавьте источник или материал с основанием")
    return value


def validate_brief(raw):
    require(isinstance(raw, dict), "Бриф должен быть объектом")
    value = deepcopy(raw)
    for key in ("company", "product", "audience", "primary_metric", "restrictions", "licence_note"):
        value[key] = text(value.get(key, ""), key, required=False)
    require(value.get("goal", "") in ("", *GOALS), "Неизвестный профиль цели")
    value.setdefault("goal", "")
    geo = value.setdefault("geo", [])
    require(isinstance(geo, list) and all(isinstance(g, str) and re.fullmatch(r"[A-Z]{2}", g) for g in geo),
            "GEO: используйте двухбуквенные коды стран")
    require(len(set(geo)) == len(geo), "GEO содержит дубликаты")
    budget = value.setdefault("budget", {})
    require(isinstance(budget, dict), "Бюджет должен быть объектом")
    number(budget.get("amount"), "Бюджет", low=0.01, optional=True)
    integer(budget.get("months"), "Период бюджета", low=1, optional=True)
    currency = budget.get("currency", "")
    require(isinstance(currency, str) and (not currency or re.fullmatch(r"[A-Z]{3}", currency)),
            "Валюта: трёхбуквенный код")
    require(budget.get("scope", "") in ("", "all_in", "fee_only"), "Неизвестный состав бюджета")
    for key, default in (("amount", None), ("months", None), ("currency", ""), ("scope", "")):
        budget.setdefault(key, default)
    integer(value.setdefault("min_followers", 100000), "Порог подписчиков")
    integer(value.setdefault("metric_max_age_days", 7), "Свежесть счётчиков", low=1)
    integer(value.setdefault("max_search_calls", 18), "Лимит поиска")
    integer(value.setdefault("max_pages", 24), "Лимит страниц")
    number(value.get("delivery_target"), "План контактов", low=0.01, optional=True)
    value.setdefault("delivery_target", None)
    topics = value.setdefault("topics", {"direct": [], "audience": [], "adjacent": []})
    require(isinstance(topics, dict), "Темы должны быть объектом")
    for key in ("direct", "audience"):
        require(isinstance(topics.get(key, []), list)
                and all(isinstance(v, str) and v.strip() for v in topics.get(key, [])), "Неверные темы поиска")
        topics.setdefault(key, [])
    require(isinstance(topics.setdefault("adjacent", []), list), "Неверные косвенные темы")
    for item in topics["adjacent"]:
        require(isinstance(item, dict), "Косвенная тема: term и reason")
        text(item.get("term"), "Косвенная тема")
        text(item.get("reason"), "Основание косвенной связи")
    if "search_preferences" in value:
        from packages.strategy.config import preferences
        value["search_preferences"] = preferences(value["search_preferences"])
    return value


def brief_missing(brief):
    missing = [label for key, label in (("company", "Компания"), ("product", "Продукт"),
               ("goal", "Цель"), ("audience", "ЦА"), ("geo", "География")) if not brief.get(key)]
    missing += [label for key, label in (("amount", "Сумма бюджета"), ("currency", "Валюта"),
                ("months", "Период бюджета"), ("scope", "Состав бюджета")) if not brief["budget"].get(key)]
    return missing


def validate_source(raw, synthetic):
    require(isinstance(raw, dict), "Источник должен быть объектом")
    item = deepcopy(raw)
    item["id"] = text(item.get("id") or identifier("src"), "ID источника", limit=100)
    item["title"] = text(item.get("title", ""), "Название источника")
    item["excerpt"] = text(item.get("excerpt", ""), "Фрагмент или содержание материала")
    item["url"] = text(item.get("url", ""), "URL", required=False, limit=3000)
    item["reference"] = text(item.get("reference", ""), "Материал", required=False, limit=1000)
    require(item["url"] or item["reference"], "Укажите URL или описание предоставленного материала")
    if item["url"]:
        require(urlparse(item["url"]).scheme in ("https", "http") and urlparse(item["url"]).hostname,
                "Разрешены только HTTP/HTTPS ссылки")
    item.setdefault("kind", "owner_material")
    require(item["kind"] in ("public", "owner_material", "provider_estimate", "synthetic"),
            "Неизвестный тип источника")
    require(synthetic or item["kind"] != "synthetic", "Синтетический источник допустим только в демо")
    item.setdefault("access", "provided_material")
    require(item["access"] in ("page_read", "provided_material", "search_lead"), "Неизвестный способ чтения")
    item["retrieved_on"] = iso_date(item.get("retrieved_on"), "Дата получения", future=False)
    for key in ("published_on", "event_on"):
        item[key] = iso_date(item.get(key), key, optional=True, future=(key == "event_on"))
    return item


def validate_candidate(raw, sources):
    require(isinstance(raw, dict), "Кандидат должен быть объектом")
    item = deepcopy(raw)
    item["id"] = text(item.get("id") or identifier("cand"), "ID кандидата", limit=100)
    item["name"] = text(item.get("name"), "Имя")
    require(item.get("kind") in KINDS, "Неизвестный тип кандидата")
    item["entity_key"] = text(item.get("entity_key") or item.get("official_url") or item["id"], "Идентичность")
    item["official_url"] = text(item.get("official_url", ""), "Официальная ссылка", required=False)
    if item["official_url"]:
        require(urlparse(item["official_url"]).scheme in ("https", "http"), "Неверная официальная ссылка")
    item["rationale"] = text(item.get("rationale", ""), "Связь с брендом", required=False)
    item["source_ids"] = refs(item.get("source_ids", []), sources)
    item.setdefault("metrics", [])
    require(isinstance(item["metrics"], list), "Счётчики должны быть списком")
    for metric in item["metrics"]:
        require(isinstance(metric, dict), "Неверный счётчик")
        text(metric.get("platform"), "Платформа")
        integer(metric.get("followers"), "Подписчики", optional=True)
        iso_date(metric.get("observed_on"), "Дата счётчика", future=False)
        refs(metric.get("evidence_ids", []), sources, required=metric.get("followers") is not None)
        require(metric.get("precision", "exact") in ("exact", "rounded", "hidden"), "Неизвестная точность")
        for key in ("lower_bound", "upper_bound"):
            integer(metric.get(key), "Граница счётчика", optional=True)
        if metric.get("lower_bound") is not None and metric.get("upper_bound") is not None:
            require(metric["lower_bound"] <= metric["upper_bound"], "Границы счётчика перепутаны")
    require(isinstance(item.setdefault("platform_scan_complete", False), bool), "Неверный статус проверки платформ")
    require(item.setdefault("queue", "needs_data") in ("priority", "alternative", "needs_data", "excluded"),
            "Неизвестная очередь")
    if item["queue"] == "excluded":
        text(item.get("exclusion_reason"), "Причина исключения")
        refs(item["source_ids"], sources, required=True)
    risk = item.setdefault("risk", {"status": "not_checked", "reason": "", "source_ids": []})
    require(isinstance(risk, dict) and risk.get("status") in RISK_STATUSES, "Неверный статус риска")
    risk["source_ids"] = refs(risk.get("source_ids", []), sources)
    if risk["status"] in ("flagged", "confirmed_block"):
        text(risk.get("reason"), "Основание риска")
        refs(risk["source_ids"], sources, required=True)
    if risk["status"] == "confirmed_block":
        require(risk.get("human_reviewed") is True, "Исключение по риску требует ручной проверки")
    return item


def validate_weights(raw):
    require(isinstance(raw, dict) and set(raw) == set(CRITERIA), "Нужны веса четырёх критериев")
    for key, value in raw.items():
        number(value, f"Вес {key}", high=1)
    require(abs(sum(raw.values()) - 1) < 1e-8, "Сумма весов должна равняться 1")
    return deepcopy(raw)


def validate_package(raw, state):
    require(isinstance(raw, dict), "Пакет должен быть объектом")
    item = deepcopy(raw)
    item["id"] = text(item.get("id") or identifier("pkg"), "ID пакета", limit=100)
    require(item.get("candidate_id") in {c["id"] for c in state["candidates"]}, "Кандидат пакета не найден")
    item["name"] = text(item.get("name"), "Название пакета")
    integer(item.get("months"), "Срок пакета", low=1)
    require(isinstance(item.get("territory"), list) and item["territory"]
            and all(isinstance(g, str) and re.fullmatch(r"[A-Z]{2}", g) for g in item["territory"]),
            "Территория пакета обязательна")
    item["deliverables"] = text(item.get("deliverables"), "Активации")
    item["rights"] = text(item.get("rights", ""), "Права и отчётность", required=False)
    item["source_ids"] = refs(item.get("source_ids", []), state["sources"])
    item["brief_version"] = state["brief_version"]
    criteria = item.setdefault("criteria", {})
    require(isinstance(criteria, dict) and set(criteria) <= set(CRITERIA), "Неизвестный критерий")
    for key in CRITERIA:
        entry = criteria.setdefault(key, {"value": None, "reason": "", "source_ids": []})
        require(isinstance(entry, dict), "Оценка критерия должна содержать value, reason, source_ids")
        number(entry.get("value"), CRITERIA[key], high=100, optional=True)
        entry["source_ids"] = refs(entry.get("source_ids", []), state["sources"])
        entry.setdefault("reason", "")
        if entry.get("value") is not None:
            text(entry["reason"], f"Обоснование: {CRITERIA[key]}")
            refs(entry["source_ids"], state["sources"], required=True)
    fee = item.setdefault("fee", {"status": "unknown", "low": None, "high": None})
    require(isinstance(fee, dict) and fee.get("status") in ("unknown", "estimate", "reported", "published"),
            "Неизвестный статус цены")
    for key in ("low", "high"):
        number(fee.get(key), "Цена", optional=True)
        fee.setdefault(key, None)
    fee["source_ids"] = refs(fee.get("source_ids", []), state["sources"])
    if fee["status"] == "unknown":
        require(fee["low"] is None and fee["high"] is None, "Неизвестная цена не может быть числом")
    else:
        number(fee["low"], "Нижняя цена")
        number(fee["high"], "Верхняя цена")
        require(fee["low"] <= fee["high"], "Диапазон цены перепутан")
        require(isinstance(fee.get("currency"), str) and re.fullmatch(r"[A-Z]{3}", fee["currency"]),
                "Валюта цены обязательна")
        iso_date(fee.get("valid_on"), "Дата цены", future=False)
        refs(fee["source_ids"], state["sources"], required=True)
        require(fee.get("basis") == "this_package", "Цена должна относиться к конкретному пакету")
        if fee["status"] == "estimate":
            text(fee.get("derivation"), "Основание оценки цены")
    extras = item.setdefault("extra_costs", {"low": None, "high": None, "complete": False, "reason": ""})
    require(isinstance(extras, dict) and isinstance(extras.get("complete", False), bool), "Неверные дополнительные расходы")
    for key in ("low", "high"):
        number(extras.get(key), "Расходы сверх гонорара", optional=True)
        extras.setdefault(key, None)
    if extras.get("complete"):
        number(extras["low"], "Нижняя сумма дополнительных расходов")
        number(extras["high"], "Верхняя сумма дополнительных расходов")
        require(extras["low"] <= extras["high"], "Диапазон дополнительных расходов перепутан")
        text(extras.get("reason"), "Основание полноты расходов")
    forecast = item.setdefault("forecast", None)
    if forecast is not None:
        require(isinstance(forecast, dict) and forecast.get("metric") in METRICS, "Неверная метрика прогноза")
        for key in ("low", "base", "high"):
            number(forecast.get(key), f"Прогноз {key}", high=100 if forecast["metric"].endswith("_rate") else None)
        require(forecast["low"] <= forecast["base"] <= forecast["high"], "Сценарии должны идти low ≤ base ≤ high")
        text(forecast.get("basis"), "Основание прогноза")
        refs(forecast.get("source_ids", []), state["sources"], required=True)
        if forecast["metric"] == "unique_reach":
            text(forecast.get("deduplication"), "Метод учёта пересечения аудитории")
    return item
