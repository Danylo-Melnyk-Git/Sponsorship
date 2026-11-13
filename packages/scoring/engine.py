"""Fixed-anchor weighted score; risks, coverage and economics stay separate."""

from datetime import date
from packages.domain.models import CRITERIA, today

from packages.scoring.weights import PROFILES, WEIGHTS_DATE, WEIGHTS_STATUS  # noqa: F401  (единый источник весов)

MODEL_VERSION = "scorecard-0.3-provisional"


def source_usable(source):
    return source and source.get("access") in ("page_read", "provided_material")


def follower_status(candidate, brief, sources):
    if candidate["kind"] not in ("influencer", "streamer"):
        return {"status": "not_applicable", "reason": "Масштаб этого типа оценивается по доступным активам"}
    if brief["min_followers"] == 0:
        return {"status": "pass", "reason": "Порог отключён в брифе"}
    source_map = {s["id"]: s for s in sources}
    latest = {}
    conflicts = set()
    for metric in candidate.get("metrics", []):
        key = metric.get("account_url") or metric["platform"]
        previous = latest.get(key)
        if previous is None or metric["observed_on"] > previous["observed_on"]:
            latest[key] = metric
            conflicts.discard(key)
        elif metric["observed_on"] == previous["observed_on"]:
            fields = ("followers", "precision", "lower_bound", "upper_bound")
            if any(metric.get(field) != previous.get(field) for field in fields):
                conflicts.add(key)
            else:
                latest[key] = metric
    if conflicts:
        return {"status": "pending", "reason": "Противоречивые счётчики на одну дату"}
    known_low = []
    for metric in latest.values():
        age = (today() - date.fromisoformat(metric["observed_on"])).days
        if age > brief["metric_max_age_days"] or metric.get("followers") is None:
            continue
        if not all(source_usable(source_map.get(sid)) for sid in metric.get("evidence_ids", [])):
            continue
        if metric.get("precision", "exact") == "rounded":
            lower, upper = metric.get("lower_bound"), metric.get("upper_bound")
            if lower is not None and lower >= brief["min_followers"]:
                return {"status": "pass", "reason": "Подтверждённая нижняя граница одной платформы"}
            known_low.append(upper is not None and upper < brief["min_followers"])
        elif metric.get("precision", "exact") == "exact":
            if metric["followers"] >= brief["min_followers"]:
                return {"status": "pass", "reason": "Порог достигнут на одной платформе"}
            known_low.append(True)
    if candidate.get("platform_scan_complete") and latest and len(known_low) == len(latest) and all(known_low):
        return {"status": "fail", "reason": "Завершена проверка платформ; порог не достигнут"}
    return {"status": "pending", "reason": "Нужны свежие счётчики; платформы не суммируются"}


def economics(package, brief):
    fee, extras, budget = package["fee"], package["extra_costs"], brief["budget"]
    result = {"fee_status": fee["status"], "fee_range": None, "full_cost_range": None,
              "budget_status": "unknown", "reason": "Цена пакета неизвестна", "currency": fee.get("currency")}
    if fee["status"] == "unknown":
        return result
    result["fee_range"] = [fee["low"], fee["high"]]
    if extras.get("complete"):
        result["full_cost_range"] = [fee["low"] + extras["low"], fee["high"] + extras["high"]]
    if budget["currency"] != fee["currency"]:
        result.update(budget_status="currency_mismatch", reason="Валюты различаются; курс не назначен")
    elif budget["months"] != package["months"]:
        result.update(budget_status="period_mismatch", reason="Периоды различаются; цена не пересчитывается молча")
    elif not set(brief["geo"]) <= set(package["territory"]):
        result.update(budget_status="territory_mismatch", reason="Права не покрывают заданную географию")
    else:
        cost_range = result["fee_range"] if budget["scope"] == "fee_only" else result["full_cost_range"]
        if cost_range is None:
            result.update(budget_status="need_full_cost", reason="Расходы сверх гонорара не установлены")
        elif budget["amount"] is None:
            result["reason"] = "Предел бюджета не установлен"
        elif cost_range[0] > budget["amount"]:
            result.update(budget_status="over_budget", reason="Известный диапазон выше бюджета")
        elif cost_range[1] <= budget["amount"]:
            result.update(budget_status="within_range", reason="Диапазон укладывается в сопоставимый бюджет")
        else:
            result.update(budget_status="overlapping_range", reason="Диапазон пересекает предел бюджета")
    return result


def evaluate(package, candidate, state, weights=None):
    weights = weights or state["weights"]
    source_map = {s["id"]: s for s in state["sources"]}
    entries, known, missing = {}, 0.0, []
    for key in CRITERIA:
        entry = package["criteria"][key]
        usable = entry.get("value") is not None and bool(entry.get("source_ids")) and all(
            source_usable(source_map.get(sid)) for sid in entry.get("source_ids", []))
        if usable:
            known += weights[key] * entry["value"]
        else:
            missing.append(key)
        entries[key] = {**entry, "weight": weights[key], "usable": usable,
                        "contribution": round(weights[key] * entry["value"], 4) if usable else None}
    missing_weight = sum(weights[k] for k in missing)
    coverage = round(1 - missing_weight, 8)
    stale = package["brief_version"] != state["brief_version"]
    followers = follower_status(candidate, state["brief"], state["sources"])
    risk = candidate["risk"]["status"]
    gates = []
    if stale:
        gates.append("brief_changed")
    if candidate["queue"] == "excluded" or risk == "confirmed_block":
        gates.append("excluded")
    if risk != "reviewed":
        gates.append("risk_review")
    if followers["status"] in ("pending", "fail"):
        gates.append("followers_" + followers["status"])
    if not candidate.get("selected"):
        gates.append("not_selected")
    if missing:
        gates.append("missing_criteria")
    score = round(known, 2) if not missing and not stale else None
    price = economics(package, state["brief"])
    if price["budget_status"] in ("over_budget", "currency_mismatch", "period_mismatch", "territory_mismatch"):
        gates.append(price["budget_status"])
    forecast = package.get("forecast")
    cpm = None
    if not stale and forecast and forecast["metric"] == "qualified_impressions" and forecast["base"] > 0 and price["full_cost_range"]:
        cpm = [round(v / forecast["base"] * 1000, 2) for v in price["full_cost_range"]]
    return {"model_version": MODEL_VERSION, "model_status": "unvalidated", "score": score,
            "interval": [round(known, 2), round(known + 100 * missing_weight, 2)],
            "interval_kind": "possible_score_bounds_not_confidence_interval",
            "coverage": coverage, "criteria": entries, "missing": missing, "stale": stale,
            "gates": gates, "risk": risk, "followers": followers,
            "rankable": score is not None and not gates,
            "economics": price, "forecast": forecast if not stale else None,
            "cost_per_1000_qualified_impressions": cpm}


def comparison(state):
    candidates = {c["id"]: c for c in state["candidates"]}
    rows = [{"package": p, "candidate": candidates[p["candidate_id"]],
             "evaluation": evaluate(p, candidates[p["candidate_id"]], state)} for p in state["packages"]]
    rows.sort(key=lambda row: (not row["evaluation"]["rankable"],
                               -(row["evaluation"]["score"] if row["evaluation"]["score"] is not None else -1),
                               row["package"]["id"]))
    rank, position, previous_score = 0, 0, None
    for row in rows:
        if row["evaluation"]["rankable"]:
            position += 1
            if row["evaluation"]["score"] != previous_score:
                rank = position
            previous_score = row["evaluation"]["score"]
            row["rank"] = rank
        else:
            row["rank"] = None
        row["sensitivity"] = {
            name: evaluate(row["package"], row["candidate"], state, profile)["score"]
            for name, profile in PROFILES.items()
        }
    return rows
