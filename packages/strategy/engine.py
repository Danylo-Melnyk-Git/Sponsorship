"""Generate reviewable partner/format hypotheses, including without names."""
from copy import deepcopy
from hashlib import sha256
from itertools import product
import json
from math import ceil

from packages.domain.models import brief_missing, validate_brief
from packages.measurement.engine import COSTS, fields, interval, number, obj
from .catalog import CATALOG, GOAL_ORDER
from .config import CAPABILITIES, preferences


def fingerprint(brief):
    return sha256(json.dumps(brief, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def draft_state(payload):
    obj(payload, "strategy input")
    fields(payload, ("title", "kind", "request", "brief"), "strategy input")
    if payload.get("kind") not in ("synthetic", "owner_brief"):
        raise ValueError("kind: synthetic или owner_brief")
    for name in ("title", "request"):
        if not isinstance(payload.get(name), str) or not payload[name].strip():
            raise ValueError(f"Нужно поле {name}; исходный запрос не заменяется догадкой")
    brief = validate_brief(payload.get("brief"))
    return {"id": "draft-" + fingerprint(brief)[:12], "revision": None, "brief_version": 1,
            "title": payload["title"], "kind": payload["kind"], "request": payload["request"],
            "brief": brief, "candidates": [], "packages": [], "search_log": [], "sources": []}


def price_conditions(brief, raw=None):
    result = {"market_price": None, "budget_fee_cap": None, "economic_fee_cap": None,
              "combined_fee_cap": None, "required_outcomes_if_full_budget_spent": None,
              "currency": brief["budget"]["currency"] or None, "months": brief["budget"]["months"],
              "notes": ["Ставка и готовность партнёра неизвестны. Потолок — условие покупателя, не рыночный диапазон."]}
    budget = brief["budget"]
    known_budget = all(budget.get(k) for k in ("amount", "currency", "months", "scope"))
    if known_budget and budget["scope"] == "fee_only":
        result["budget_fee_cap"] = [budget["amount"], budget["amount"]]
        result["notes"].append("Лимит относится только к гонорару; полные расходы будут выше.")
    if raw is None:
        result["notes"].append("Для расчёта цены нужны прочие расходы, их полнота, маржа, гипотеза добавочного результата и целевой ROI именно этого формата.")
        return result
    obj(raw, "profile economics")
    fields(raw, ("currency", "months", "geo", "other_cost_scope_complete", "cost_scope_note", "other_costs",
                 "margin_definition", "incremental_outcome_definition", "margin_per_outcome", "incremental_outcomes", "target_roi"), "profile economics")
    if not known_budget:
        raise ValueError("Перед привязкой экономики уточните сумму, валюту, период и состав бюджета")
    number(budget["amount"], "budget.amount", 0.01)
    if type(raw.get("months")) is not int or raw.get("currency") != budget["currency"] or raw.get("months") != budget["months"] or raw.get("geo") != brief["geo"]:
        raise ValueError("Экономика профиля не совпадает с валютой, периодом или GEO брифа")
    if type(raw.get("other_cost_scope_complete")) is not bool:
        raise ValueError("other_cost_scope_complete: нужен bool")
    for key in ("cost_scope_note", "margin_definition", "incremental_outcome_definition"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise ValueError(f"Нужно определить {key}")
    costs = obj(raw.get("other_costs"), "other_costs")
    if set(costs) != set(COSTS) - {"rights_fee"}:
        raise ValueError("Нужны семь непересекающихся категорий прочих затрат")
    parsed = {k: interval(v, k, 0) for k, v in costs.items()}
    margin = interval(raw.get("margin_per_outcome"), "margin_per_outcome", 0)
    outcomes = interval(raw.get("incremental_outcomes"), "incremental_outcomes")
    r = number(raw.get("target_roi"), "target_roi", 0, 100)
    if not raw["other_cost_scope_complete"] or any(v is None for v in parsed.values()):
        result["notes"].append("Прочие затраты неполны/неизвестны: экономический потолок и порог результата не рассчитаны.")
        return result
    other = [sum(v[i] for v in parsed.values()) for i in (0, 1)]
    result["other_costs"] = other
    result["target_roi"] = r
    if budget["scope"] == "all_in":
        result["budget_fee_cap"] = [budget["amount"] - other[1], budget["amount"] - other[0]]
        full_budget = [budget["amount"], budget["amount"]]
    else:
        full_budget = [budget["amount"] + other[0], budget["amount"] + other[1]]
    if result["budget_fee_cap"][1] < 0:
        result["notes"].append("Даже прочие затраты превышают весь бюджет: пакет нужно сократить до обсуждения гонорара.")
    if margin is not None and margin[0] > 0:
        result["required_outcomes_if_full_budget_spent"] = [ceil(full_budget[0]*(1+r)/margin[1]), ceil(full_budget[1]*(1+r)/margin[0])]
    if margin is not None and outcomes is not None:
        contributions = [n*m for n, m in product(outcomes, margin)]
        cap = [min(contributions)/(1+r)-other[1], max(contributions)/(1+r)-other[0]]
        result["economic_fee_cap"] = cap
        result["combined_fee_cap"] = [min(cap[i], result["budget_fee_cap"][i]) for i in (0, 1)]
        result["notes"].append("Границы по допущениям, не доверительный интервал. Отрицательный потолок означает отсутствие допустимого неотрицательного гонорара в соответствующем сценарии.")
    else:
        result["notes"].append("Добавочный результат/маржа неизвестны; финансовая окупаемость не установлена.")
    return result


def strategy(state, economics=None):
    from packages.connectors.legacy import search_plan
    brief = state["brief"]
    config = preferences(brief.get("search_preferences"))
    sha = fingerprint(brief)
    inputs = {}
    if economics is not None:
        fields(economics, ("brief_sha256", "profiles"), "economics binding")
        if economics.get("brief_sha256") != sha:
            raise ValueError("Экономика относится к другому брифу; перечитайте изменения и пересмотрите допущения, не заменяйте хеш механически")
        inputs = obj(economics.get("profiles"), "economics.profiles")
        if set(inputs) - {row["id"] for row in CATALOG}:
            raise ValueError("Экономика содержит неизвестный формат")
    plan = search_plan(state)
    profiles, excluded = [], []
    order = GOAL_ORDER.get(brief["goal"], [r["id"] for r in CATALOG])
    for catalog_row in CATALOG:
        row = deepcopy(catalog_row)
        row["categories"] = [c for c in row["categories"] if c in config["categories"]]
        if row["id"] not in config["formats"] or not row["categories"]:
            excluded.append({"id": row["id"], "name": row["name"], "reason": "Вне явно выбранных форматов или категорий"})
            continue
        required = row["requires"] + (["conversion_tracking"] if brief["goal"] == "action" else
                                        ["brand_measurement"] if brief["goal"] in ("awareness", "trust") else [])
        unavailable = [CAPABILITIES[k] for k in required if config["capabilities"].get(k) is False]
        unknown = [CAPABILITIES[k] for k in required if config["capabilities"].get(k) is None]
        row["feasibility"] = "blocked_by_resources" if unavailable else "conditional" if unknown or not brief["goal"] else "resources_declared"
        row["unavailable_resources"], row["unknown_resources"] = unavailable, unknown
        row["audience_requirement"] = brief["audience"] or "ЦА не определена: сформулировать проверяемую гипотезу, не приписывать доход/возраст всей аудитории"
        row["geography_requirement"] = brief["geo"] or ["Уточнить GEO аудитории и прав"]
        row["product_role"] = (f'Проверить, как «{brief["product"]}» помогает заявленной аудитории в этой механике.'
                               if brief["product"] else "Продукт не описан: содержательная роль пока неизвестна.")
        row["metric"] = brief.get("primary_metric") or {"awareness": "Предложение: прирост выбранного вида знания/связи бренда в п.п.",
                      "trust": "Предложение: изменение заранее выбранной опросной метрики отношения/доверия",
                      "action": "Предложение: добавочное целевое действие и маржинальный вклад в фиксированном окне"}.get(brief["goal"], "Выбрать цель до предпочтения формата")
        row["audience_evidence"] = "Нужны доля и размер целевой аудитории, период и метод, активность, пересечения и история именно брендированных контактов. Страна автора и подписчики этого не доказывают."
        row["topic_hypotheses"] = ([{"lane": lane, "term": term, "reason": "Тема из брифа; соответствие аудитории и продукту проверить"}
                                   for lane in ("direct", "audience") if lane in config["lanes"] for term in brief["topics"][lane]] +
                                  ([{"lane": "adjacent", **item} for item in brief["topics"]["adjacent"]] if "adjacent" in config["lanes"] else []))
        row["price"] = price_conditions(brief, inputs.get(row["id"]))
        row["search_cells"] = [t["id"] for t in plan["scheduled"] if t["category"] in row["categories"]]
        profiles.append(row)
    # Validate even economics attached to a currently filtered-out format.
    for key in set(inputs) - {p["id"] for p in profiles}:
        price_conditions(brief, inputs[key])
    profiles.sort(key=lambda p: (p["feasibility"] == "blocked_by_resources", order.index(p["id"])))
    deferred = [{"id": p["id"], "name": p["name"], "reason": "Не входит в выбранное число показанных профилей; кандидат не отклонён", "feasibility": p["feasibility"]} for p in profiles[config["max_profiles"]:]]
    profiles = profiles[:config["max_profiles"]]
    logs = state.get("search_log", [])
    current = [s for s in logs if s.get("brief_version") == state["brief_version"]]
    completed_ids = {s.get("plan_query_id") for s in current if s["status"] == "completed"}
    failed_ids = {s.get("plan_query_id") for s in current if s["status"] == "failed"} - completed_ids
    used_calls = sum(s["status"] in ("completed", "failed") for s in logs)
    used_pages = sum(s.get("pages_read", 0) for s in logs)
    remaining_calls = max(0, brief["max_search_calls"]-used_calls)
    remaining_pages = max(0, brief["max_pages"]-used_pages)
    next_queries = [t for t in plan["scheduled"] if t["id"] not in completed_ids | failed_ids][:remaining_calls] if remaining_pages else []
    retry_queries = [t for t in plan["scheduled"] if t["id"] in failed_ids]
    candidate_count = len(state.get("candidates", []))
    execution = ("Поиск ещё не зарегистрирован для этой версии брифа." if not current else
                 "Есть журнал поиска; записи об исполнении не доказывают полноту рынка и пригодность кандидатов.")
    return {"schema_version": "partner-strategy-1", "title": state["title"], "kind": state["kind"],
            "research_id": state["id"], "revision": state.get("revision"), "brief_version": state["brief_version"],
            "brief_sha256": sha, "request": state.get("request", ""), "brief": deepcopy(brief),
            "economics_inputs": deepcopy(economics), "missing_brief_fields": brief_missing(brief),
            "status": "profile_hypotheses", "candidate_count": candidate_count,
            "fallback": ("Конкретные кандидаты пока не записаны. Ниже профиль потребности, а не найденный партнёр. " if not candidate_count else
                         f"Записано кандидатов: {candidate_count}. Профили не заменяют ручной отбор и не присваивают одобрение. ") + execution,
            "order_meaning": "Порядок — редакционная гипотеза под цель и заявленный ресурс; не рейтинг эффективности. Неизвестные предпочтения не выдаются за решение владельца.",
            "profiles": profiles, "deferred_profiles": deferred, "excluded_formats": excluded, "search_plan": plan,
            "execution": {"network_executed_by_this_command": False, "recorded_calls_all_versions": used_calls,
                          "remaining_calls": remaining_calls, "remaining_pages": remaining_pages,
                          "completed_current_plan_cells": len(completed_ids & {t["id"] for t in plan["scheduled"]}),
                          "next_queries": next_queries, "retry_requires_review": retry_queries},
            "hard_constraints": {"restrictions": brief["restrictions"] or "Не заданы; уточнить",
                                 "min_followers": brief["min_followers"], "follower_gate_kinds": ["influencer", "streamer"],
                                 "note": "Порог не суммируется по платформам; риск, возрастные/географические ограничения и ручной допуск не ослабляются автоматически."},
            "next_decision": "Выбрать проверяемые гипотезы формата, подтвердить аудиторию/ресурс, затем искать конкретных правообладателей и получать реальные условия через человека."}
