"""Scenario arithmetic and descriptive measurement, not a causal/forecast model."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
from itertools import product
import json
from math import ceil, isfinite, sqrt
import re
from statistics import NormalDist

VERSION = "measurement-1"
COSTS = ("rights_fee", "production", "activation", "paid_media", "measurement",
         "travel_fees_taxes", "internal_work", "other")
COST_LABELS = dict(zip(COSTS, ("Права / гонорар", "Производство", "Активация", "Продвижение",
                             "Измерение", "Поездки, комиссии, налоги", "Работа команды", "Прочее")))


def obj(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name}: нужен объект")
    return value


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: нужен непустой текст")
    return value


def number(value, name, minimum=-1e12, maximum=1e12):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not isfinite(value)):
        raise ValueError(f"{name}: нужно конечное число, не строка/bool")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name}: вне диапазона {minimum}…{maximum}")
    return value


def integer(value, name, minimum=0, maximum=10**12):
    number(value, name, minimum, maximum)
    if int(value) != value:
        raise ValueError(f"{name}: нужно целое число")
    return int(value)


def dated(value, name):
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text(value, name)):
            raise ValueError("format")
        return date.fromisoformat(text(value, name))
    except ValueError as exc:
        raise ValueError(f"{name}: нужна дата YYYY-MM-DD") from exc


def evidence(data, name):
    text(data.get("source"), f"{name}.source")
    dated(data.get("as_of"), f"{name}.as_of")
    text(data.get("note"), f"{name}.note")


def fields(data, allowed, name):
    obj(data, name)
    extra = set(data) - set(allowed)
    if extra:
        raise ValueError(f"{name}: неизвестные поля: " + ", ".join(sorted(extra)))


def interval(data, name, minimum=-1e12):
    obj(data, name)
    fields(data, ("low", "high", "status", "source", "as_of", "note"), name)
    evidence(data, name)
    if data.get("status") not in ("assumption", "estimate", "observed", "unknown"):
        raise ValueError(f"{name}: неизвестный status")
    if data["status"] == "unknown":
        if data.get("low") is not None or data.get("high") is not None:
            raise ValueError(f"{name}: unknown требует low/high=null")
        return None
    low = number(data.get("low"), f"{name}.low", minimum)
    high = number(data.get("high"), f"{name}.high", minimum)
    if low > high:
        raise ValueError(f"{name}: low больше high")
    return [low, high]


def bounds(values):
    values = list(values)
    return [min(values), max(values)]


def economic(data):
    obj(data, "economics")
    fields(data, ("cost_scope_complete", "cost_scope_note", "margin_definition", "incremental_outcome_definition",
                  "target_roi", "costs", "margin_per_outcome", "incremental_outcomes", "alternative_net"), "economics")
    if type(data.get("cost_scope_complete")) is not bool:
        raise ValueError("economics.cost_scope_complete: нужен bool")
    text(data.get("cost_scope_note"), "cost_scope_note")
    text(data.get("margin_definition"), "margin_definition")
    text(data.get("incremental_outcome_definition"), "incremental_outcome_definition")
    r = number(data.get("target_roi"), "target_roi", 0, 100)
    costs = obj(data.get("costs"), "costs")
    if set(costs) != set(COSTS):
        raise ValueError("costs: нужны ровно восемь категорий; неприменимость = явный 0 с причиной")
    parsed = {key: interval(costs[key], key, 0) for key in COSTS}
    margin = interval(data.get("margin_per_outcome"), "margin_per_outcome", 0)
    outcomes = interval(data.get("incremental_outcomes"), "incremental_outcomes")
    alternative = (interval(data["alternative_net"], "alternative_net")
                   if data.get("alternative_net") is not None else None)
    result = {"known_cost_subtotal": [sum(v[i] for v in parsed.values() if v is not None) for i in (0, 1)],
              "total_cost": None, "break_even_outcomes": None, "target_outcomes": None,
              "incremental_contribution": None, "net": None, "roi": None, "fee_cap": None,
              "versus_alternative": None, "sensitivity": [], "blockers": [], "target_roi": r,
              "conclusion": "insufficient_inputs", "causal_roi_verified": False,
              "meaning": "Границы сценариев при заданных допущениях; не прогноз и не доверительный интервал."}
    if not data["cost_scope_complete"]:
        result["blockers"].append("Состав полных затрат не подтверждён составителем.")
    for key, value in parsed.items():
        if value is None:
            result["blockers"].append(f"Неизвестные расходы: {COST_LABELS[key]}.")
    if not result["blockers"]:
        result["total_cost"] = result["known_cost_subtotal"]
    if margin is None or margin[0] <= 0:
        result["blockers"].append("Для конечного порога нужна положительная маржа во всём диапазоне.")
    if result["total_cost"] is None:
        return result
    total = result["total_cost"]
    if margin is not None and margin[0] > 0:
        result["break_even_outcomes"] = [ceil(total[0] / margin[1]), ceil(total[1] / margin[0])]
        result["target_outcomes"] = [ceil(total[0] * (1 + r) / margin[1]),
                                     ceil(total[1] * (1 + r) / margin[0])]
    if outcomes is None or margin is None:
        result["blockers"].append("Сценарий результата/маржи отсутствует; порог не доказывает достижимость.")
        return result
    contribution = bounds(n * m for n, m in product(outcomes, margin))
    result["incremental_contribution"] = contribution
    result["net"] = [contribution[0] - total[1], contribution[1] - total[0]]
    if total[0] > 0:
        # Corner enumeration matters when contribution is negative.
        result["roi"] = bounds((m - c) / c for m, c in product(contribution, total))
    else:
        result["blockers"].append("Затраты могут быть нулевыми: конечный диапазон ROI не определён.")
    other = [sum(parsed[k][i] for k in COSTS if k != "rights_fee") for i in (0, 1)]
    result["fee_cap"] = [contribution[0] / (1 + r) - other[1],
                          contribution[1] / (1 + r) - other[0]]
    if alternative is not None:
        result["versus_alternative"] = [result["net"][0] - alternative[1], result["net"][1] - alternative[0]]
    mid_margin, mid_n = sum(margin) / 2, sum(outcomes) / 2
    result["sensitivity"] = sorted([
        {"input": "Добавочные результаты", "net_swing": (outcomes[1] - outcomes[0]) * abs(mid_margin)},
        {"input": "Маржа на результат", "net_swing": (margin[1] - margin[0]) * abs(mid_n)},
        *({"input": COST_LABELS[k], "net_swing": v[1] - v[0]} for k, v in parsed.items())
    ], key=lambda row: row["net_swing"], reverse=True)
    result["conclusion"] = ("nonnegative_in_all_bounds" if result["net"][0] >= 0 else
                            "negative_in_all_bounds" if result["net"][1] < 0 else "depends_on_assumptions")
    return result


def wilson(successes, size, alpha):
    z = NormalDist().inv_cdf(1 - alpha / 2)
    p = successes / size
    denominator = 1 + z * z / size
    center = (p + z * z / (2 * size)) / denominator
    half = z * sqrt(p * (1 - p) / size + z * z / (4 * size * size)) / denominator
    return [0. if successes == 0 else max(0., center - half),
            1. if successes == size else min(1., center + half)]


def survey(data):
    obj(data, "survey")
    fields(data, ("source", "as_of", "note", "metric", "population", "period", "design_note", "alpha",
                  "treatment", "control", "design"), "survey")
    evidence(data, "survey")
    for key in ("metric", "population", "period", "design_note"):
        text(data.get(key), f"survey.{key}")
    alpha = number(data.get("alpha"), "survey.alpha", .0001, .5)
    groups = []
    for name in ("treatment", "control"):
        group = obj(data.get(name), name)
        fields(group, ("n", "yes"), name)
        n = integer(group.get("n"), name + ".n", 1)
        x = integer(group.get("yes"), name + ".yes", 0, n)
        groups.append((x, n))
    design = data.get("design")
    if design not in ("randomized_individual", "observational_independent", "clustered_or_weighted_or_paired"):
        raise ValueError("survey.design: неподдерживаемое значение")
    p1, p0 = (x / n for x, n in groups)
    result = {"treatment_rate": p1, "control_rate": p0, "difference_pp": 100 * (p1 - p0),
              "relative_difference": (p1 - p0) / p0 if p0 else None, "interval_pp": None,
              "confidence_level": 1 - alpha, "causal_effect_verified": False,
              "interpretation": "Наблюдаемая разница; интервал не устраняет смещения выбора и измерения."}
    if design == "clustered_or_weighted_or_paired":
        result["interpretation"] = "Только сырая разница долей. Для весов, кластеров или пар нужен отдельный анализ; интервал не рассчитан."
    else:
        lo1, hi1 = wilson(*groups[0], alpha)
        lo0, hi0 = wilson(*groups[1], alpha)
        result["interval_pp"] = [100 * (p1 - p0 - sqrt((p1 - lo1)**2 + (hi0 - p0)**2)),
                                  100 * (p1 - p0 + sqrt((p0 - lo0)**2 + (hi1 - p1)**2))]
        result["method"] = "Newcombe, независимые биномиальные доли, Wilson без поправки непрерывности"
    return result


def sample_plan(data):
    obj(data, "sample_plan")
    fields(data, ("source", "as_of", "note", "baseline_rate", "effect_pp", "alpha", "power", "response_rate"), "sample_plan")
    evidence(data, "sample_plan")
    p0 = number(data.get("baseline_rate"), "baseline_rate", .000001, .999999)
    effect = number(data.get("effect_pp"), "effect_pp", .000001, 100) / 100
    p1 = p0 + effect
    if p1 >= 1:
        raise ValueError("baseline_rate + effect_pp/100 должно быть меньше 1")
    alpha = number(data.get("alpha"), "alpha", .0001, .5)
    power = number(data.get("power"), "power", .500001, .9999)
    response = number(data.get("response_rate"), "response_rate", .000001, 1)
    avg = (p0 + p1) / 2
    za, zb = NormalDist().inv_cdf(1 - alpha / 2), NormalDist().inv_cdf(power)
    n = ceil((za * sqrt(2 * avg * (1 - avg)) + zb * sqrt(p0 * (1 - p0) + p1 * (1 - p1)))**2 / effect**2)
    return {"completed_per_arm": n, "completed_total": n * 2,
            "invitations_per_arm": ceil(n / response),
            "meaning": "Нормальное приближение для двух равных независимых групп и одного двустороннего теста долей, с пренебрежением дальним хвостом. Не для кластеров/панели/взвешивания; не гарантия мощности реального дизайна.",
            "small_expected_cells": min(n*p0, n*(1-p0), n*p1, n*(1-p1)) < 10}


def audience(data):
    obj(data, "audience")
    fields(data, ("source", "as_of", "note", "population_definition", "period", "population", "reach_a", "reach_b",
                  "overlap", "target_marginal_shares"), "audience")
    evidence(data, "audience")
    text(data.get("population_definition"), "population_definition")
    text(data.get("period"), "audience.period")
    population = integer(data.get("population"), "population", 1)
    a = integer(data.get("reach_a"), "reach_a", 0, population)
    b = integer(data.get("reach_b"), "reach_b", 0, population)
    overlap = data.get("overlap")
    lower, upper = max(0, a + b - population), min(a, b)
    if overlap is not None:
        overlap = integer(overlap, "overlap", lower, upper)
        lower = upper = overlap
    result = {"overlap": [lower, upper], "union": [a+b-upper, a+b-lower],
              "new_beyond_a": [b-upper, b-lower],
              "meaning": "Границы множеств для одной популяции и окна, не доверительные интервалы. Входы — уникальные люди, не показы/подписчики."}
    shares = data.get("target_marginal_shares")
    if shares is not None:
        if not isinstance(shares, list) or len(shares) < 2:
            raise ValueError("target_marginal_shares: нужны минимум две доли одной популяции")
        for p in shares:
            number(p, "target_marginal_shares", 0, 1)
        result["joint_target_share"] = [max(0, sum(shares) - len(shares) + 1), min(shares)]
    return result


def agreement(data):
    obj(data, "ratings")
    fields(data, ("source", "as_of", "note", "rater_a", "rater_b", "rubric_version", "rows"), "ratings")
    evidence(data, "ratings")
    for key in ("rater_a", "rater_b", "rubric_version"):
        text(data.get(key), key)
    if data["rater_a"] == data["rater_b"]:
        raise ValueError("Нужны разные оценщики")
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("ratings.rows: нужен непустой список")
    differences, missing, ids = [], [], set()
    for row in rows:
        obj(row, "ratings.row")
        fields(row, ("id", "a", "b"), "ratings.row")
        key = text(row.get("id"), "ratings.row.id")
        if key in ids:
            raise ValueError("Повтор ratings.row.id")
        ids.add(key)
        a, b = row.get("a"), row.get("b")
        for value in (a, b):
            if value is not None:
                number(value, "rating", 0, 100)
        if a is None or b is None:
            missing.append(key)
        else:
            differences.append({"id": key, "a": a, "b": b, "gap": abs(a-b), "signed_gap": a-b})
    n = len(differences)
    return {"paired": n, "missing": missing, "exact_agreement": sum(r["gap"] == 0 for r in differences)/n if n else None,
            "mean_absolute_gap": sum(r["gap"] for r in differences)/n if n else None,
            "mean_signed_gap": sum(r["signed_gap"] for r in differences)/n if n else None,
            "rows": sorted(differences, key=lambda r: r["gap"], reverse=True),
            "meaning": "Описательное расхождение по введённой шкале 0–100; не процент объективности, не межэкспертная надёжность и не утверждение среднего балла."}


def analyze(payload):
    obj(payload, "input")
    if payload.get("schema_version") != VERSION:
        raise ValueError(f"Нужна schema_version={VERSION}")
    if payload.get("kind") not in ("synthetic", "planning"):
        raise ValueError("kind: synthetic или planning; модуль не удостоверяет причинный ROI")
    text(payload.get("title"), "title")
    scope = obj(payload.get("scope"), "scope")
    fields(scope, ("currency", "territory", "outcome_unit", "period_start", "period_end"), "scope")
    for key in ("currency", "territory", "outcome_unit"):
        text(scope.get(key), "scope." + key)
    if not re.fullmatch(r"[A-Z]{3}", scope["currency"]):
        raise ValueError("currency: код валюты из трёх заглавных букв; конвертации нет")
    if dated(scope.get("period_start"), "period_start") > dated(scope.get("period_end"), "period_end"):
        raise ValueError("Период перевёрнут")
    allowed = {"schema_version", "kind", "title", "scope", "economics", "survey", "sample_plan", "audience", "ratings"}
    if set(payload) - allowed:
        raise ValueError("Неизвестные верхнеуровневые поля: " + ", ".join(sorted(set(payload)-allowed)))
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    result = {"schema_version": VERSION, "kind": payload["kind"], "title": payload["title"],
              "scope": deepcopy(scope), "input_sha256": sha256(encoded).hexdigest(),
              "inputs": deepcopy(payload)}
    for key, function in (("economics", economic), ("survey", survey), ("sample_plan", sample_plan),
                          ("audience", audience), ("ratings", agreement)):
        if key in payload:
            result[key] = function(payload[key])
    if not any(key in result for key in ("economics", "survey", "sample_plan", "audience", "ratings")):
        raise ValueError("Нужен хотя бы один расчётный блок")
    json.dumps(result, allow_nan=False)
    return result
