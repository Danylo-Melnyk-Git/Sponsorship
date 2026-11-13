"""План поиска и предварительный отбор; сеть выполняет исследователь в Codex."""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
VERSION = "0.1"
KINDS = {"influencer", "streamer", "athlete", "musician", "expert", "team",
         "club", "league", "federation", "tournament", "event", "race", "podcast"}
BUCKETS = {
    "creators": {"es": "creadores y divulgadores con canales propios",
                 "pt": "criadores e divulgadores com canais próprios",
                 "en": "creators and experts with their own channels"},
    "athletes": {"es": "deportistas de disciplinas especializadas",
                 "pt": "atletas de modalidades especializadas",
                 "en": "athletes in specialist sports"},
    "music": {"es": "músicos artistas y sellos independientes",
              "pt": "músicos artistas e selos independentes",
              "en": "musicians artists and independent labels"},
    "teams": {"es": "clubes equipos ligas y federaciones",
              "pt": "clubes equipes ligas e federações",
              "en": "clubs teams leagues and federations"},
    "events": {"es": "torneos eventos carreras y festivales",
               "pt": "torneios eventos corridas e festivais",
               "en": "tournaments events races and festivals"},
    "gaming_media": {"es": "esports streamers podcasts y medios temáticos",
                    "pt": "esports streamers podcasts e mídia temática",
                    "en": "esports streamers podcasts and specialist media"},
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def integer(value):
    return type(value) is int and value >= 0


def iso_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"Некорректная дата: {value!r}") from None


def canonical_url(value):
    p = urlsplit(value)
    require(p.scheme in {"http", "https"} and bool(p.hostname)
            and p.username is None and p.password is None,
            f"Нужен публичный HTTP(S) URL без credentials: {value!r}")
    # Query сохраняется: в нём могут быть ID страницы или канала.
    return urlunsplit((p.scheme.lower(), p.netloc.lower(),
                      p.path.rstrip("/"), p.query, ""))


def settings(brief, threshold=None):
    s = {"min_followers": 100000, "follower_gate_kinds": ["influencer", "streamer"],
         "metric_max_age_days": 7, "max_search_calls": 18, "max_pages": 24,
         "num_results": 5}
    s.update(brief.get("advanced", {}))
    if threshold is not None:
        s["min_followers"] = threshold
    for key in ("min_followers", "metric_max_age_days", "max_search_calls", "max_pages"):
        require(integer(s[key]), f"{key}: нужен целый неотрицательный параметр")
    require(integer(s["num_results"]) and 1 <= s["num_results"] <= 25,
            "num_results: нужно целое число от 1 до 25")
    require(isinstance(s["follower_gate_kinds"], list)
            and set(s["follower_gate_kinds"]) <= KINDS, "Неизвестные follower_gate_kinds")
    return s


def validate_brief(b):
    require(b.get("schema_version") == "1.0", "Неизвестная версия брифа")
    for key in ("id", "company", "goal", "audience", "geo", "budget", "topics"):
        require(key in b, f"Бриф: отсутствует {key}")
    require(isinstance(b["company"], dict) and bool(b["company"].get("name")),
            "Нужна компания или явно условный бренд")
    require(all(isinstance(b[k], str) and bool(b[k].strip()) for k in ("id", "goal", "audience")),
            "ID, цель и ЦА должны быть непустыми строками")
    require(isinstance(b["geo"], list) and b["geo"]
            and all(isinstance(g, str) and len(g) == 2 and g.isupper() for g in b["geo"]),
            "geo: список кодов стран из двух заглавных букв")
    budget = b["budget"]
    require(number(budget["amount"]) and budget["amount"] > 0, "Бюджет должен быть > 0")
    require(integer(budget["months"]) and budget["months"] > 0, "Нужен период бюджета")
    require(isinstance(budget["currency"], str) and len(budget["currency"]) == 3,
            "Нужна валюта бюджета")
    require(budget["scope"] in {"all_in", "fee_only"}, "scope: all_in или fee_only")
    reserve = budget.get("non_fee_costs")
    require(reserve is None or number(reserve), "non_fee_costs: число или null")
    require(reserve is None or reserve <= budget["amount"], "Расходы превышают бюджет")
    for lane in ("direct", "audience", "adjacent"):
        require(isinstance(b["topics"].get(lane), list), f"topics.{lane}: нужен список")
    for t in b["topics"]["direct"] + b["topics"]["audience"]:
        require(isinstance(t, str) and bool(t.strip()), "Пустая тема поиска")
    for t in b["topics"]["adjacent"]:
        require(isinstance(t, dict) and bool(t.get("term")) and bool(t.get("reason")),
                "Косвенная тема требует term и reason")
    require(any(b["topics"].values()), "Нужна хотя бы одна тема поиска")
    settings(b)


def make_plan(brief, packs, threshold=None):
    validate_brief(brief)
    s = settings(brief, threshold)
    locales = []
    for geo in brief["geo"]:
        require(geo in packs["countries"], f"Нет GEO-пакета {geo}; добавьте его в pakety-geo.json")
        pack = packs["countries"][geo]
        for lang in pack["languages"]:
            require(lang in {"es", "pt", "en"}, f"Нет шаблона для языка {lang}")
            locales.append((geo, pack, lang))
    lanes = [("direct", brief["topics"]["direct"]),
             ("audience", brief["topics"]["audience"]),
             ("adjacent", [x["term"] for x in brief["topics"]["adjacent"]])]
    tasks = []
    # Все углы на основном языке идут перед дополнительными языками.
    for language_pass in range(max(len(p["languages"]) for _, p, _ in locales)):
        for lane, terms in lanes:
            if not terms:
                continue
            for bucket, labels in BUCKETS.items():
                for geo, pack, lang in locales:
                    if pack["languages"].index(lang) != language_pass:
                        continue
                    tasks.append(search_task(geo, pack, lang, bucket, labels, lane, terms, s))
    scheduled = tasks[:s["max_search_calls"]]
    scheduled_ids = {t["id"] for t in scheduled}
    return {"schema_version": "1.0", "tool_version": VERSION, "brief_id": brief["id"],
            "brief_kind": brief.get("kind", "unspecified"), "settings": s,
            "collaboration_budget": brief["budget"], "network_executed": False,
            "research_cost_usd": None,
            "adjacent_bridges": brief["topics"]["adjacent"],
            "scheduled": scheduled,
            "deferred": [t for t in tasks if t["id"] not in scheduled_ids],
            "source_seeds": {geo: packs["countries"][geo].get("source_seeds", [])
                             for geo in brief["geo"]},
            "next_steps": ["Выполнить scheduled через доступный поисковый MCP и записать журнал.",
                           "Прочитать выбранные страницы; максимум max_pages относится к страницам, а не числу batch-вызовов.",
                           "Вручную заполнить досье с фрагментами, датами и статусами.",
                           "Запустить review; проверить пробелы и провести ручную модерацию."]}


def search_task(geo, pack, lang, bucket, labels, lane, terms, s):
    topic = ", ".join(terms)
    label = labels[lang]
    templates = {
        "es": f"Páginas oficiales de {label} vinculados a {topic} en {pack['name']}, con contenido propio, audiencia y colaboraciones con marcas o auspiciadores",
        "pt": f"Páginas oficiais de {label} ligados a {topic} no {pack['name']}, com conteúdo próprio, público e parcerias com marcas ou patrocinadores",
        "en": f"Official pages of {label} connected to {topic} in {pack['name']}, with original content, audience and brand partnerships",
    }
    return {"id": f"{geo}-{lang}-{bucket}-{lane}", "geo": geo,
            "language": lang, "category": bucket, "lane": lane, "status": "planned",
            "tool": "mcp__codex_apps__exa_web_search_exa",
            "arguments": {"query": templates[lang], "numResults": s["num_results"],
                          "objective": "Discover identities and official URLs. Include niche and audience-adjacent properties. Search results are leads only: fetch sources. Do not invent audience GEO, price or availability; do not apply a follower threshold to clubs or events."}}


def validate_corpus(corpus, today):
    require(corpus.get("schema_version") == "1.0", "Неизвестная версия досье")
    require(isinstance(corpus.get("evidence"), list), "Нужен реестр evidence")
    evidence = {}
    for e in corpus["evidence"]:
        require(e["id"] not in evidence, "Повтор ID источника")
        canonical_url(e["url"])
        require(iso_day(e["retrieved_on"]) <= today, "Источник получен в будущем")
        require(bool(e.get("excerpt")) and bool(e.get("summary")), "Нужны фрагмент и резюме")
        require(e.get("access") == "page_read", "Сниппет поиска не является доказательством")
        evidence[e["id"]] = e

    def refs(obj, required=False):
        ids = obj.get("evidence_ids", [])
        require(isinstance(ids, list) and all(x in evidence for x in ids),
                f"Неизвестный ID evidence: {ids!r}")
        require(not required or bool(ids), "Утверждение требует источника")

    ids, entities, cleaned, duplicates = set(), {}, [], []
    for c in corpus["candidates"]:
        require(c["id"] not in ids, "Повтор ID кандидата")
        ids.add(c["id"])
        require(c["kind"] in KINDS, "Неизвестный тип кандидата")
        canonical_url(c["official_url"])
        require(bool(c.get("entity_key")), "Нужен проверенный ключ идентичности entity_key")
        for claim in c.get("topic_claims", []):
            require(bool(claim.get("term")), "Нет темы утверждения")
            refs(claim, True)
        refs(c.get("geo_context", {}), bool(c.get("geo_context", {}).get("countries")))
        refs(c.get("scale", {}), c.get("scale", {}).get("level", "unknown") != "unknown")
        for m in c.get("metrics", []):
            require(bool(m.get("platform")) and bool(m.get("account_url")), "Нет платформы/аккаунта")
            canonical_url(m["account_url"])
            refs(m, m.get("followers") is not None)
            for key in ("followers", "lower_bound", "upper_bound"):
                require(m.get(key) is None or integer(m[key]), f"{key}: число подписчиков должно быть целым")
            require(m.get("precision") in {"exact", "rounded", "unknown"}, "Нет precision")
            if m.get("observed_on"):
                require(iso_day(m["observed_on"]) <= today, "Метрика измерена в будущем")
            if m.get("lower_bound") is not None and m.get("upper_bound") is not None:
                require(m["lower_bound"] <= m["upper_bound"], "Перепутаны границы подписчиков")
        audience = c.get("audience_geo", {})
        require(audience.get("basis", "unknown") in {"unknown", "proxy", "provider_estimate", "reported"},
                "Неизвестное основание GEO аудитории")
        refs(audience, audience.get("basis", "unknown") != "unknown")
        for key in ("risk", "availability"):
            refs(c.get(key, {}))
        require(c.get("risk", {}).get("status", "not_checked") in
                {"not_checked", "flagged", "reviewed", "confirmed_block"}, "Неизвестный статус риска")
        if c.get("risk", {}).get("status") == "confirmed_block":
            refs(c["risk"], True)
            require(c["risk"].get("human_reviewed") is True, "Риск-исключение требует проверки человеком")
        opp_ids = set()
        require(bool(c.get("opportunities")), "Нужна хотя бы одна гипотеза пакета")
        for o in c["opportunities"]:
            require(o["id"] not in opp_ids, "Повтор ID пакета")
            opp_ids.add(o["id"])
            require(o["scope"] in {"limited_nonexclusive", "annual_nonexclusive", "global_exclusive"},
                    "Неизвестный scope пакета")
            cost = o["cost"]
            hypothesis = o.get("budget_hypothesis")
            if hypothesis:
                require(hypothesis.get("assessment") in {"plausible", "unlikely", "unknown"},
                        "Неизвестная бюджетная гипотеза")
                require(bool(hypothesis.get("brief_id")) and number(hypothesis.get("budget_amount"))
                        and bool(hypothesis.get("reason")) and bool(hypothesis.get("assumptions")),
                        "Бюджетная гипотеза требует бриф, сумму, основание и допущения")
            require(cost["status"] in {"unknown", "estimate", "published"}, "Неизвестный статус цены")
            refs(cost, cost["status"] != "unknown")
            if cost["status"] != "unknown":
                require(number(cost["low"]) and number(cost["high"]) and cost["low"] <= cost["high"],
                        "Некорректный ценовой диапазон")
                require(integer(cost["months"]) and cost["months"] > 0, "Нет периода цены")
                require(cost.get("cost_basis") in {"fee_only", "all_in"}, "Нет состава цены")
                require(cost.get("source_price_kind") in
                        {"sponsorship_package", "creator_activation", "ambassadorship", "appearance", "rights_license"},
                        "Цена билета/курса/товара не является ставкой за сотрудничество")
                require(cost.get("valid_on") is not None and iso_day(cost["valid_on"]) <= today,
                        "Нет даты проверки цены")
                require(cost.get("valid_until") is not None, "Нет срока пригодности цены")
                iso_day(cost["valid_until"])
                require(cost.get("derivation") or cost["status"] == "published",
                        "Оценка цены требует объяснения расчёта")
            else:
                require(cost.get("low") is None and cost.get("high") is None,
                        "Неизвестная цена не может содержать числа")
        if c["entity_key"] in entities:
            previous = entities[c["entity_key"]]
            a, b = copy.deepcopy(previous), copy.deepcopy(c)
            a.pop("id"); b.pop("id")
            require(a == b, f"Конфликт досье одной сущности {c['entity_key']}; объедините вручную")
            duplicates.append({"id": c["id"], "duplicate_of": previous["id"]})
        else:
            entities[c["entity_key"]] = c
            cleaned.append(c)
    return evidence, cleaned, duplicates


def follower_gate(candidate, s, today):
    if candidate["kind"] not in s["follower_gate_kinds"] or s["min_followers"] == 0:
        return {"status": "not_applicable", "reason": "Порог не применяется к этому типу"}
    latest, observations = {}, {}
    for m in candidate.get("metrics", []):
        if not m.get("observed_on"):
            continue
        account = canonical_url(m["account_url"])
        key = (account, m["observed_on"])
        value = (m["followers"], m["precision"], m.get("lower_bound"), m.get("upper_bound"))
        if key in observations and observations[key] != value:
            return {"status": "pending", "reason": "Конфликт счётчиков одного аккаунта"}
        observations[key] = value
        if account not in latest or m["observed_on"] > latest[account]["observed_on"]:
            latest[account] = m
    usable = []
    for m in latest.values():
        if m["followers"] is None or (today - iso_day(m["observed_on"])).days > s["metric_max_age_days"]:
            continue
        lo = m["followers"] if m["precision"] == "exact" else m.get("lower_bound")
        hi = m["followers"] if m["precision"] == "exact" else m.get("upper_bound")
        usable.append((m, lo, hi))
    if any(lo is not None and lo >= s["min_followers"] for _, lo, _ in usable):
        return {"status": "pass", "reason": "Порог достигнут на одном отдельном аккаунте",
                "platforms": sorted({m["platform"] for m, lo, _ in usable
                                     if lo is not None and lo >= s["min_followers"]})}
    complete = candidate.get("platform_scan_complete") is True
    account_count = len({canonical_url(m["account_url"]) for m in candidate.get("metrics", [])})
    all_observed = bool(account_count) and len(usable) == account_count
    if complete and all_observed and all(hi is not None and hi < s["min_followers"] for _, _, hi in usable):
        return {"status": "fail", "reason": "На каждой проверенной платформе ниже порога; суммы нет"}
    return {"status": "pending", "reason": "Нет полного свежего подтверждения отдельной платформы"}


def fit_result(candidate, brief):
    topics = {x["term"].casefold() for x in candidate.get("topic_claims", [])}
    for lane in ("direct", "audience", "adjacent"):
        requested = brief["topics"][lane]
        terms = [x["term"] for x in requested] if lane == "adjacent" else requested
        hits = [x for x in terms if x.casefold() in topics]
        if hits:
            return {"lane": lane, "terms": hits, "status": "hypothesis",
                    "bridges": [x for x in requested if isinstance(x, dict) and x["term"] in hits]}
    return {"lane": "unknown", "terms": [], "status": "needs_human_mapping"}


def budget_result(candidate, opportunity, brief, today):
    cost, b = opportunity["cost"], brief["budget"]
    if cost["status"] == "unknown":
        scale = candidate.get("scale", {}).get("level", "unknown")
        hypothesis = opportunity.get("budget_hypothesis", {})
        applicable = (hypothesis.get("brief_id") == brief["id"]
                      and hypothesis.get("budget_amount") == b["amount"]
                      and hypothesis.get("currency") == b["currency"]
                      and hypothesis.get("months") == b["months"]
                      and hypothesis.get("budget_scope") == b["scope"])
        if opportunity["scope"] == "global_exclusive":
            status = "global_exclusive_requires_quote"
        elif hypothesis and not applicable:
            status = "reassess_budget_hypothesis"
        elif applicable and hypothesis.get("assessment") == "plausible":
            status = "plausible_unpriced"
        elif applicable and hypothesis.get("assessment") == "unlikely":
            status = "unlikely_unpriced"
        elif opportunity["scope"] == "limited_nonexclusive" and scale in {"local", "national", "niche"}:
            status = "limited_package_to_price"
        else:
            status = "unknown_price"
        return {"status": status, "confidence": "hypothesis", "price_range": None,
                "hypothesis": hypothesis if applicable else None,
                "reason": (hypothesis["reason"] if applicable else
                           "Ограниченный пакет можно исследовать; без бюджетной гипотезы доступность по цене не установлена")}
    result = {"status": "incomparable", "confidence": cost["status"],
              "price_range": [cost["low"], cost["high"]], "reason": ""}
    if iso_day(cost["valid_until"]) < today:
        result.update(status="stale_price", reason="Истёк срок пригодности ценового наблюдения")
    elif cost.get("currency") != b["currency"] or cost["months"] != b["months"] or cost.get("scope_match") is not True:
        result["reason"] = "Валюта, период или права/территория пакета не сопоставимы"
    else:
        cap = b["amount"]
        if b["scope"] == "all_in" and cost["cost_basis"] == "fee_only":
            if b.get("non_fee_costs") is None:
                result.update(status="need_full_cost", reason="Неизвестны расходы сверх гонорара")
                return result
            cap -= b["non_fee_costs"]
        elif b["scope"] == "fee_only" and cost["cost_basis"] == "all_in":
            result["reason"] = "Полная стоимость не разложена на гонорар и остальные расходы"
            return result
        status = "within_observed_range" if cost["high"] <= cap else (
            "over_observed_range" if cost["low"] > cap else "overlapping_range")
        result.update(status=status, comparison_ceiling=cap,
                      reason="Сравнение указанного диапазона; цена не является гарантией сделки")
    return result


def review(brief, corpus, today, threshold=None):
    validate_brief(brief)
    s = settings(brief, threshold)
    evidence, candidates, duplicates = validate_corpus(corpus, today)
    rows = []
    for c in candidates:
        gate, fit = follower_gate(c, s, today), fit_result(c, brief)
        ag = c.get("audience_geo", {})
        geo = "supported" if (ag.get("basis") in {"reported", "provider_estimate"}
                               and set(brief["geo"]) <= set(ag.get("countries", []))) else "needs_audience_geo"
        for o in c["opportunities"]:
            budget = budget_result(c, o, brief, today)
            missing = list(c.get("open_questions", []))
            if gate["status"] == "pending":
                missing.append("Проверить порог на отдельной платформе")
            if geo != "supported":
                missing.append("Проверить целевое GEO аудитории; происхождение кандидата недостаточно")
            if fit["lane"] == "unknown":
                missing.append("Обосновать связь с брендом/ЦА")
            risk = c.get("risk", {}).get("status", "not_checked")
            if risk != "reviewed":
                missing.append("Провести проверку риска человеком")
            if c.get("availability", {}).get("status", "unknown") != "reported":
                missing.append("Менеджеру выяснить доступность и условия")
            if budget["status"] not in {"within_observed_range", "over_observed_range"}:
                missing.append("Уточнить цену и полную стоимость конкретного пакета")
            window = o.get("event_on")
            if window and iso_day(window) < today:
                missing.append("Эта дата события прошла; нужна новая редакция/дата")
            if gate["status"] == "fail" or risk == "confirmed_block" or budget["status"] == "over_observed_range":
                segment = "excluded"
            elif gate["status"] == "pending" or fit["lane"] == "unknown" or risk == "flagged" or budget["status"] in {"global_exclusive_requires_quote", "reassess_budget_hypothesis", "unlikely_unpriced"} or (window and iso_day(window) < today):
                segment = "needs_data"
            else:
                segment = "research_priority" if fit["lane"] in {"direct", "audience"} else "alternative"
            row_refs = sorted({eid for obj in c.get("topic_claims", []) + c.get("metrics", [])
                               + [c.get("geo_context", {}), ag, c.get("risk", {}),
                                  c.get("scale", {}), c.get("availability", {}), o["cost"]]
                               for eid in obj.get("evidence_ids", [])})
            rows.append({"candidate_id": c["id"], "name": c["name"], "kind": c["kind"],
                         "official_url": c["official_url"], "opportunity_id": o["id"],
                         "package": o["description"], "package_status": "hypothesis",
                         "segment": segment, "fit": fit, "followers": gate,
                         "audience_geo": geo, "budget": budget, "risk": risk,
                         "missing": list(dict.fromkeys(missing)), "evidence_ids": row_refs,
                         "human_moderation_required": True})
    # Это очередь проверки, не численный рейтинг эффективности.
    order = {"research_priority": 0, "alternative": 1, "needs_data": 2, "excluded": 3}
    rows.sort(key=lambda r: (order[r["segment"]],
                            r["budget"]["status"] == "global_exclusive_requires_quote",
                            r["candidate_id"], r["opportunity_id"]))
    return {"schema_version": "1.0", "tool_version": VERSION, "as_of": today.isoformat(),
            "brief_id": brief["id"], "brief_kind": brief.get("kind", "unspecified"),
            "status": "preliminary_research_queue", "settings": s,
            "input_kind": corpus.get("kind", "unspecified"), "evidence": list(evidence.values()),
            "rows": rows, "duplicates": duplicates, "numeric_suitability_score": None,
            "market_price_model_validated": False, "research_cost_usd": corpus.get("research_cost_usd"),
            "network_execution_log": corpus.get("execution_log", {}),
            "planned_search_coverage": "not_assessed"}


def markdown(report):
    def clean(s):
        return str(s).replace("|", "/").replace("\n", " ")
    lines = ["# Предварительная очередь исследования", "",
             f"Дата: {report['as_of']}. Бриф: {report['brief_id']} ({report['brief_kind']}).",
             "Пакеты и соответствие бренду — гипотезы. Итоговый выбор требует ручной модерации.",
             f"Порог: {report['settings']['min_followers']} на одной платформе. Численный рейтинг не рассчитан.",
             "", "| Объект | Пакет | Очередь | Связь | Подписчики | Бюджет | GEO аудитории |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in report["rows"]:
        lines.append("| " + " | ".join(clean(x) for x in [
            f"[{r['name']}]({r['official_url']})", r["package"], r["segment"],
            r["fit"]["lane"], r["followers"]["status"], r["budget"]["status"], r["audience_geo"]]) + " |")
    for r in report["rows"]:
        lines += ["", f"## {r['name']} / {r['opportunity_id']}", "",
                  r["budget"]["reason"], "", "Вопросы: " + "; ".join(r["missing"]) + ".",
                  "Источники: " + ", ".join(r["evidence_ids"]) + "."]
    lines += ["", "## Реестр источников", ""]
    for e in report["evidence"]:
        lines.append(f"- {e['id']}: [{e['summary']}]({e['url']}); получено {e['retrieved_on']}; дата публикации: {e.get('published_on') or 'не установлена'}.")
    lines += ["", "Покрытие сгенерированного плана: не оценено. Расходы провайдера: "
              + ("не переданы" if report["research_cost_usd"] is None else str(report["research_cost_usd"])) + "."]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["plan", "review"])
    p.add_argument("--brief", required=True)
    p.add_argument("--corpus")
    p.add_argument("--geo-packs", default=str(ROOT / "pakety-geo.json"))
    p.add_argument("--min-followers", type=int)
    p.add_argument("--as-of", default=date.today().isoformat())
    p.add_argument("--out", required=True, help="Новый JSON-файл; существующий не перезаписывается")
    p.add_argument("--markdown", help="Новый Markdown-файл для review")
    args = p.parse_args()
    try:
        brief = read_json(args.brief)
        if args.command == "plan":
            result = make_plan(brief, read_json(args.geo_packs), args.min_followers)
            require(args.markdown is None, "--markdown относится к review")
        else:
            require(args.corpus is not None, "review требует --corpus")
            result = review(brief, read_json(args.corpus), iso_day(args.as_of), args.min_followers)
        paths = [Path(args.out)] + ([Path(args.markdown)] if args.markdown else [])
        require(len({x.resolve() for x in paths}) == len(paths), "JSON и Markdown требуют разных путей")
        require(all(not x.exists() for x in paths), "Выход уже существует; выберите новый файл")
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
        with paths[0].open("x", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        if args.markdown:
            with paths[1].open("x", encoding="utf-8") as f:
                f.write(markdown(result))
        print(f"Готово: {len(result.get('scheduled', result.get('rows', [])))} записей; {paths[0]}")
    except (ValueError, KeyError, TypeError, OSError) as e:
        print(f"Ошибка входных данных: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
