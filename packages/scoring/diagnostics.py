"""Read-only bounded sensitivity analysis. No probability model or decisions."""

from contextlib import closing
from itertools import combinations
import json
from pathlib import Path
import sqlite3

from packages.domain.models import CRITERIA, number, today, utcnow, validate_weights
from packages.scoring.engine import MODEL_VERSION, evaluate

EPS = 1e-8
DIAGNOSTIC_VERSION = "bounded-sensitivity-0.1"

GATE_LABELS = {
    "brief_changed": "Изменён бриф: сначала пересмотреть пакет",
    "excluded": "Исключён или имеет подтверждённый блок",
    "risk_review": "Нужна ручная проверка риска",
    "followers_pending": "Нужны актуальные данные о масштабе",
    "followers_fail": "Порог масштаба не выполнен",
    "not_selected": "Нет ручного выбора кандидата",
    "missing_criteria": "Не хватает пригодных оценок",
    "over_budget": "Известный диапазон выше бюджета",
    "currency_mismatch": "Валюта не сопоставима с бюджетом",
    "period_mismatch": "Период не сопоставим с брифом",
    "territory_mismatch": "Пакет не покрывает географию брифа",
}
RELATION_LABELS = {
    "a_strictly_above": "Первый выше во всей области",
    "b_strictly_above": "Второй выше во всей области",
    "reversal_possible": "Порядок может измениться",
    "always_tied": "Равенство во всей области",
    "a_weakly_above": "Первый не ниже; возможно равенство",
    "b_weakly_above": "Второй не ниже; возможно равенство",
}


def load_read_only(database, research_id):
    """Opening a report must not create a DB or run schema migrations."""
    if str(database).startswith('firestore://'):
        from packages.domain.storage import open_store
        return open_store(database).get(research_id)
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        row = db.execute("SELECT document FROM research WHERE id=?", (research_id,)).fetchone()
    if row is None:
        raise KeyError("Исследование не найдено")
    return json.loads(row[0])


def weight_domain(weights, radius_pp):
    validate_weights(weights)
    number(radius_pp, "Отклонение веса, п.п.", high=100)
    radius = radius_pp / 100
    return {key: [max(0., value - radius), min(1., value + radius)]
            for key, value in weights.items()}


def extreme(values, domain, maximize=False):
    """Exact linear optimum on a box intersected with sum(weights) == 1.

    Start at all lower bounds, then allocate the remaining mass in order of
    coefficient. The exchange argument proves optimality: shifting mass from
    a worse coefficient to an unsaturated better one cannot worsen the result.
    """
    weights = {key: bounds[0] for key, bounds in domain.items()}
    remaining = 1 - sum(weights.values())
    for key in sorted(values, key=lambda key: values[key], reverse=maximize):
        addition = min(max(0., remaining), domain[key][1] - weights[key])
        weights[key] += addition
        remaining -= addition
    if abs(remaining) > EPS:
        raise ValueError("Область весов не содержит сумму 100%")
    return sum(weights[k] * values[k] for k in values), weights


def relation(low, high):
    if low > EPS:
        return "a_strictly_above"
    if high < -EPS:
        return "b_strictly_above"
    if low < -EPS and high > EPS:
        return "reversal_possible"
    if abs(low) <= EPS and abs(high) <= EPS:
        return "always_tied"
    return "a_weakly_above" if low >= -EPS else "b_weakly_above"


def scope_gates(package, brief):
    # Scope exists even when economics() exits early because the fee is unknown.
    result = []
    if brief["budget"]["months"] != package["months"]:
        result.append("period_mismatch")
    if not set(brief["geo"]) <= set(package["territory"]):
        result.append("territory_mismatch")
    return result


def diagnose(state, weight_radius_pp, score_radius=0):
    """All output is derived from one revision; never mutate the input."""
    number(score_radius, "Отклонение оценки, баллы", high=100)
    weights = state["weights"]
    domain = weight_domain(weights, weight_radius_pp)
    candidates = {c["id"]: c for c in state["candidates"]}
    rows, requests = [], []
    for package in state["packages"]:
        candidate = candidates[package["candidate_id"]]
        evaluation = evaluate(package, candidate, state)
        gates = list(dict.fromkeys(evaluation["gates"] + scope_gates(package, state["brief"])))
        low, high = {}, {}
        for key, entry in evaluation["criteria"].items():
            low[key] = max(0., entry["value"] - score_radius) if entry["usable"] else 0.
            high[key] = min(100., entry["value"] + score_radius) if entry["usable"] else 100.
        eligible = not any(g != "missing_criteria" for g in gates)
        bounds = None if evaluation["stale"] else [extreme(low, domain)[0], extreme(high, domain, True)[0]]
        row = {
            "package_id": package["id"], "package_version": package["package_version"],
            "candidate": candidate["name"], "package": package["name"],
            "base_score": sum(weights[k] * e["value"] for k, e in evaluation["criteria"].items()) if evaluation["score"] is not None else None,
            "base_bounds": evaluation["interval"] if not evaluation["stale"] else None,
            "stress_bounds": bounds, "coverage": evaluation["coverage"],
            "missing": evaluation["missing"], "gates": gates,
            "eligible_for_diagnostic": eligible, "base_rank": None,
            "score_inputs": {k: e["value"] if e["usable"] else None for k, e in evaluation["criteria"].items()},
            "input_bounds": {k: [low[k], high[k]] for k in CRITERIA},
            "economics": evaluation["economics"],
            "fee_status": package["fee"]["status"],
            "conditional_rank_bounds": None,
        }
        rows.append(row)
        for gate in gates:
            if gate != "missing_criteria":
                requests.append({"group": "gate", "package_id": package["id"], "field": gate,
                                 "question": GATE_LABELS.get(gate, gate), "score_width": None})
        if evaluation["stale"]:
            continue
        if eligible:
            for key in evaluation["missing"]:
                requests.append({"group": "evidence", "package_id": package["id"], "field": key,
                                 "question": "Получить основание для критерия: " + CRITERIA[key],
                                 "score_width": 100 * weights[key]})
        if package["fee"]["status"] in ("unknown", "estimated") or evaluation["economics"]["budget_status"] != "within_range":
            requests.append({"group": "commercial", "package_id": package["id"], "field": "price",
                             "question": "Уточнить действующую цену, состав затрат и сопоставимость условий через менеджера",
                             "score_width": None})

    # Competition ranks on unrounded arithmetic; missing data never get a rank.
    complete = [r for r in rows if r["eligible_for_diagnostic"] and not r["missing"]]
    raw_scores = {r["package_id"]: sum(weights[k] * r["score_inputs"][k] for k in CRITERIA) for r in complete}
    for row in complete:
        row["base_rank"] = 1 + sum(value > raw_scores[row["package_id"]] + EPS for value in raw_scores.values())

    pool = [row for row in rows if row["eligible_for_diagnostic"]]
    pairs = []
    for a, b in combinations(pool, 2):
        lower = {k: a["input_bounds"][k][0] - b["input_bounds"][k][1] for k in CRITERIA}
        upper = {k: a["input_bounds"][k][1] - b["input_bounds"][k][0] for k in CRITERIA}
        minimum, min_weights = extreme(lower, domain)
        maximum, max_weights = extreme(upper, domain, True)
        pairs.append({"a": a["package_id"], "b": b["package_id"], "gap_bounds": [minimum, maximum],
                      "relation": relation(minimum, maximum),
                      "conditional_on_missing": bool(a["missing"] or b["missing"]),
                      "min_witness": {"weights": min_weights, "a_scores": {k: a["input_bounds"][k][0] for k in CRITERIA},
                                      "b_scores": {k: b["input_bounds"][k][1] for k in CRITERIA}},
                      "max_witness": {"weights": max_weights, "a_scores": {k: a["input_bounds"][k][1] for k in CRITERIA},
                                      "b_scores": {k: b["input_bounds"][k][0] for k in CRITERIA}}})

    for row in pool:
        guaranteed_above = possible_above = 0
        for pair in pairs:
            if row["package_id"] == pair["a"]:
                lo, hi = (-pair["gap_bounds"][1], -pair["gap_bounds"][0])
            elif row["package_id"] == pair["b"]:
                lo, hi = pair["gap_bounds"]
            else:
                continue
            guaranteed_above += lo > EPS
            possible_above += hi > EPS
        row["conditional_rank_bounds"] = [1 + guaranteed_above, 1 + possible_above]

    # Fixed-base threshold is an explanation, never a recommendation to invent a score.
    leaders = [r for r in complete if r["base_rank"] == 1]
    for request in requests:
        if request["group"] != "evidence":
            continue
        row = next(r for r in rows if r["package_id"] == request["package_id"])
        if len(row["missing"]) == 1 and leaders and weights[request["field"]] > EPS:
            leader_score = raw_scores[leaders[0]["package_id"]]
            known = sum(weights[k] * value for k, value in row["score_inputs"].items() if value is not None)
            threshold = (leader_score - known) / weights[request["field"]]
            request["tie_score_at_base_weights"] = threshold
            request["can_reach_base_leader"] = threshold <= 100 + EPS
            request["leader_ids"] = [r["package_id"] for r in leaders]
    order = {"gate": 0, "evidence": 1, "commercial": 2}
    requests.sort(key=lambda r: (order[r["group"]], -(r["score_width"] or 0), r["package_id"], r["field"]))

    # Dependencies only: several fields citing one document are not independent checks.
    dependencies = []
    for source in state["sources"]:
        fields = [f"{p['id']}:{k}" for p in state["packages"] for k, entry in p["criteria"].items()
                  if source["id"] in entry.get("source_ids", [])]
        if fields:
            dependencies.append({"source_id": source["id"], "title": source["title"],
                                 "access": source["access"], "fields": fields})

    return {
        "diagnostic_version": DIAGNOSTIC_VERSION, "model_version": MODEL_VERSION,
        "generated_at": utcnow(), "as_of_date": today().isoformat(),
        "research_id": state["id"], "research_revision": state["revision"],
        "brief_version": state["brief_version"], "weights_version": state["weights_version"],
        "title": state["title"], "kind": state["kind"], "weights": dict(weights),
        "weight_radius_pp": weight_radius_pp, "score_radius": score_radius, "weight_domain": domain,
        "rows": rows, "pairs": pairs, "requests": requests, "source_dependencies": dependencies,
        "limits": [
            "Экспериментальная диагностика; веса, шкалы и пределы отклонений не валидированы.",
            "Границы возможных баллов не являются доверительным интервалом или вероятностью успеха.",
            "Оценки внутри заданных интервалов варьируются независимо; общие ошибки источников не моделируются.",
            "Границы мест консервативны: отдельные парные крайности могут быть несовместимы одновременно.",
            "Неизвестная цена, срок действия оффера и фактическая доступность требуют отдельной проверки.",
            "Диагностика не меняет данные, веса, ручной выбор, риск или решения C-level.",
        ],
    }
