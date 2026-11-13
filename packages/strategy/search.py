"""Fair scheduling with separate allocation, execution and evidence coverage."""
from collections import Counter

from .config import preferences
from .catalog import CATALOG


def build_plan(state, prototype, packs):
    brief = state["brief"]
    config = preferences(brief.get("search_preferences"))
    compatible = {c for row in CATALOG if row["id"] in config["formats"] for c in row["categories"]}
    categories = [c for c in config["categories"] if c in compatible]
    settings = {key: brief[key] for key in ("min_followers", "metric_max_age_days", "max_search_calls", "max_pages")}
    settings.update(follower_gate_kinds=["influencer", "streamer"], num_results=5)
    lanes = {key: brief["topics"][key] for key in ("direct", "audience")}
    lanes["adjacent"] = [item["term"] for item in brief["topics"]["adjacent"]]
    tasks, missing, unsupported = [], [], []
    if not brief["geo"]:
        missing.append("География поиска")
    if not any(lanes[k] for k in config["lanes"]):
        missing.append("Хотя бы одна публичная тема в выбранных углах поиска")
    if not categories:
        missing.append("Выбранные категории не поддерживают выбранные форматы; пересмотреть сочетание")
    for geo in brief["geo"]:
        if geo not in packs["countries"]:
            unsupported.append(geo)
    locales = [(geo, packs["countries"][geo], config["languages"] or packs["countries"][geo]["languages"])
               for geo in brief["geo"] if geo in packs["countries"]]
    # Keep the first language pass before secondary translations, without
    # starving one geography, lane or category within a pass.
    for language_pass in range(max((len(langs) for _, _, langs in locales), default=0)):
        pending = []
        for lane in config["lanes"]:
            if not lanes[lane]:
                continue
            for category in categories:
                for geo, pack, languages in locales:
                    if language_pass < len(languages):
                        pending.append(prototype.search_task(geo, pack, languages[language_pass], category,
                                                             prototype.BUCKETS[category], lane, lanes[lane], settings))
        if config["order"] == "focused":
            tasks.extend(pending)
            continue
        counts = {key: Counter() for key in ("geo", "lane", "category")}
        while pending:
            index = min(range(len(pending)), key=lambda i: tuple(counts[key][pending[i][key]] for key in counts) + (i,))
            task = pending.pop(index)
            tasks.append(task)
            for key in counts:
                counts[key][task[key]] += 1
    # No pages budget means a readable-evidence search cannot be scheduled.
    limit = brief["max_search_calls"] if brief["max_pages"] > 0 else 0
    scheduled, deferred = tasks[:limit], tasks[limit:]
    return {"schema_version": "1.0", "tool_version": "strategy-search-1", "brief_id": f"{state['id']}-brief-{state['brief_version']}",
            "brief_kind": state["kind"], "network_executed": False, "research_cost_usd": None,
            "settings": settings, "search_preferences": config, "effective_categories": categories, "collaboration_budget": brief["budget"],
            "adjacent_bridges": brief["topics"]["adjacent"], "scheduled": scheduled, "deferred": deferred,
            "missing_for_search": missing, "unsupported_geographies": unsupported,
            "scope": "Предварительная разведка; бюджет, цель и ЦА требуют отдельного уточнения, если не заданы.",
            "allocation": {key: dict(Counter(t[key] for t in scheduled)) for key in ("geo", "language", "lane", "category")},
            "source_seeds": {geo: pack.get("source_seeds", []) for geo, pack, _ in locales},
            "next_steps": ["Проверить фактический остаток лимитов и выполненные ID перед сетевым вызовом.",
                           "Сгенерированный запрос — черновик. Проверить перевод публичных тем и не передавать закрытые сведения.",
                           "Прочитать первичные страницы; логировать попытки, даты, доступ и неизвестные расходы.",
                           "После разведки: отдельные запросы на аудиторию, права, измерение и опровергающие свидетельства.",
                           "Не менять жёсткие ограничения и порог подписчиков без решения владельца."]}
