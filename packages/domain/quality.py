"""Evidence readiness and draft department requests, without human decisions."""

from copy import deepcopy
from datetime import date

from .models import CRITERIA, brief_missing, identifier, iso_date, number, refs, require, text, today, utcnow
from packages.scoring.engine import comparison, source_usable
from packages.connectors.legacy import search_plan

METHODS = {"descriptive": "Наблюдаемые результаты", "randomized": "Рандомизированное сравнение",
           "geo_experiment": "Географический эксперимент", "difference_in_differences": "Разность изменений"}


def evidence(ids, state, required=False):
    refs(ids, state["sources"], required=required)
    sources = {s["id"]: s for s in state["sources"]}
    require(all(source_usable(sources[sid]) for sid in ids), "Поисковая находка не является доказательством")
    return deepcopy(ids)


def save_measurement(state, payload, actor):
    item = {}
    for key in ("metric", "unit", "population", "owner", "collection", "deduplication", "baseline",
                "control", "assignment", "confounders", "analysis", "uncertainty", "data_access",
                "cost_scope", "margin_definition", "limitations"):
        item[key] = text(payload.get(key, ""), key, required=key in ("metric", "unit"))
    item["method"] = payload.get("method", "descriptive")
    require(item["method"] in METHODS, "Неизвестный дизайн измерения")
    item["start"] = iso_date(payload.get("start"), "Начало измерения", optional=True)
    item["end"] = iso_date(payload.get("end"), "Конец измерения", optional=True)
    if item["start"] and item["end"]:
        require(item["start"] <= item["end"], "Окно измерения перепутано")
    item["target"] = number(payload.get("target"), "Целевое значение", optional=True,
                            high=100 if item["metric"].endswith("_rate") else None)
    item["source_ids"] = evidence(payload.get("source_ids", []), state)
    campaign = state.get("campaign")
    item.update(id=identifier("measurement"), version=len(state.get("measurement_plans", [])) + 1,
                brief_version=campaign["baseline"]["brief_version"] if campaign else state["brief_version"],
                campaign_id=campaign["id"] if campaign else None, at=utcnow(), actor=actor)
    state.setdefault("measurement_plans", []).append(item)


def measurement_review(state):
    campaign = state.get("campaign")
    plans = state.get("measurement_plans", [])
    current = [p for p in plans if (p.get("campaign_id") == campaign["id"] if campaign else
               p.get("campaign_id") is None and p["brief_version"] == state["brief_version"])]
    plan = current[-1] if current else deepcopy(campaign.get("measurement_baseline")) if campaign else None
    missing = [] if plan else ["План измерения для текущей версии"]
    if plan:
        for key, label in (("population", "Целевая популяция"), ("owner", "Владелец сбора"),
                           ("collection", "Источник и порядок сбора"), ("start", "Начало окна"),
                           ("end", "Конец окна"), ("data_access", "Доступ и допустимое использование"),
                           ("limitations", "Ограничения интерпретации")):
            if not plan.get(key):
                missing.append(label)
        if not plan.get("source_ids"):
            missing.append("Материал с основанием плана")
        if plan["metric"] == "unique_reach" and not plan["deduplication"]:
            missing.append("Удаление пересечений аудитории")
        if plan["method"] != "descriptive":
            for key, label in (("baseline", "Исходное сравнение"), ("control", "Контрольная группа/рынок"),
                               ("assignment", "Формирование групп и перетекание"),
                               ("confounders", "Параллельные активности и внешние факторы"),
                               ("analysis", "Метод оценки эффекта"), ("uncertainty", "Неопределённость и размер выборки")):
                if not plan[key]:
                    missing.append(label)
    if not plan:
        claim_scope = "Уровень результата не выбран: решите, нужно ли подтвердить исполнение, описательное изменение или причинную добавочность."
    elif plan["method"] == "descriptive":
        claim_scope = "Описательный уровень: можно сообщить о доставке или наблюдаемом изменении; этот дизайн сам по себе не устанавливает причинную добавочность или ROI."
    else:
        claim_scope = "Сравнительный дизайн заявлен и требует проверки аналитиком; причинный вывод требует проверить сопоставимость, перетекание, выполнение протокола и анализ данных. ROI также требует добавочной маржи и полных затрат."
    return {"plan": deepcopy(plan), "status": "draft" if missing else "specified_for_review",
            "missing": missing, "historical_versions": len(plans), "empirical_validation": "not_performed",
            "claim_scope": claim_scope,
            "roi": {"status": "not_calculated", "value": None},
            "boundary": "Заполненность полей не подтверждает пригодность дизайна, фактическое выполнение или результат. " + claim_scope}


def record_assessment(state, payload, actor):
    package = next((p for p in state["packages"] if p["id"] == payload.get("package_id")), None)
    require(package is not None, "Пакет оценки не найден")
    require(package["brief_version"] == state["brief_version"], "Сначала пересмотрите пакет под текущий бриф")
    item = {"assessor": text(payload.get("assessor"), "Оценщик"),
            "rubric_version": text(payload.get("rubric_version"), "Версия рубрики"),
            "independence_note": text(payload.get("independence_note"), "Как выполнена самостоятельная оценка"),
            "package_id": package["id"], "brief_version": state["brief_version"],
            "package_version": package.get("package_version", 1), "weights_version": state["weights_version"]}
    raw = payload.get("criteria")
    require(isinstance(raw, dict) and set(raw) == set(CRITERIA), "Оценка должна содержать четыре критерия")
    item["criteria"] = {}
    for key in CRITERIA:
        entry = raw[key]
        require(isinstance(entry, dict), "Неверный критерий оценки")
        value = number(entry.get("value"), key, high=100, optional=True)
        item["criteria"][key] = {"value": value, "reason": text(entry.get("reason"), key),
                                 "source_ids": evidence(entry.get("source_ids", []), state, required=value is not None)}
    previous = [a for a in state.get("assessments", []) if a["package_id"] == package["id"] and assessment_current(a, state, package)
                and a["assessor"].casefold() == item["assessor"].casefold()]
    if previous:
        require(payload.get("supersedes") == previous[-1]["id"], "Новая оценка должна явно ссылаться на заменяемую запись")
        item["supersedes"] = previous[-1]["id"]
    item.update(id=identifier("assessment"), at=utcnow(), actor=actor)
    state.setdefault("assessments", []).append(item)


def assessment_current(item, state, package):
    return (item["brief_version"] == state["brief_version"] and
            item["package_version"] == package.get("package_version", 1) and
            item["weights_version"] == state["weights_version"])


def assessment_review(state, package):
    current = [a for a in state.get("assessments", []) if a["package_id"] == package["id"]
               and assessment_current(a, state, package)]
    latest = {}
    for item in current:
        latest[item["assessor"].casefold()] = item
    assessments = list(latest.values())
    rubrics = sorted({a["rubric_version"] for a in assessments})
    compatible = len(rubrics) == 1
    criteria = {}
    for key in CRITERIA:
        values = [a["criteria"][key]["value"] for a in assessments if a["criteria"][key]["value"] is not None]
        criteria[key] = {"count": len(values), "range": [min(values), max(values)] if values and compatible else None,
                         "spread": max(values) - min(values) if len(values) >= 2 and compatible else None}
    return {"package_id": package["id"], "assessments": deepcopy(assessments), "assessor_count": len(assessments),
            "rubrics": rubrics, "comparable": compatible, "criteria": criteria,
            "status": "needs_second_assessor" if len(assessments) < 2 else
                      "rubric_mismatch" if not compatible else "requires_discussion",
            "boundary": "Имена и независимость заявлены пользователем; это не аутентификация и не валидация модели."}


def readiness(state, as_of=None):
    current = as_of or today()
    requests = []

    def add(code, department, title, question, acceptance, entity="project", priority="P1"):
        requests.append({"id": f"{code}:{entity}", "code": code, "department": department, "priority": priority,
                         "entity": entity, "title": title, "question": question, "acceptance": acceptance,
                         "status": "draft_not_assigned", "assignee": None, "due": None,
                         "research_id": state["id"], "expected_revision": state["revision"]})

    missing = brief_missing(state["brief"])
    if missing:
        add("brief", "Владелец бренда / Sponsorship", "Уточнить бриф", "Уточнить: " + ", ".join(missing),
            "Ответ отделяет фактические ограничения от гипотез; указаны валюта, период и состав бюджета.", priority="P0")
    if not state["brief"].get("primary_metric"):
        add("goal_metric", "Brand / Analytics", "Выбрать метрику цели", "Каким показателем и в каком окне проверяем основную цель?",
            "Есть определение метрики, единица, популяция, владелец и метод сбора.", priority="P0")
    log = [s for s in state["search_log"] if s.get("brief_version") == state["brief_version"]]
    plan = search_plan(state) if state.get("entry_mode") != "signed_import" else {"scheduled": [], "deferred": []}
    scheduled = plan["scheduled"]
    completed = {s.get("plan_query_id") for s in log if s["status"] == "completed"}
    uncovered = [q["id"] for q in scheduled if q["id"] not in completed]
    if uncovered:
        add("search_coverage", "Research / Country Manager", "Проверить покрытие поиска",
            "В журнале нет завершённых запросов с ID плана: " + ", ".join(uncovered),
            "Фактический запрос, ID плана, попытки чтения, даты, доступ, расходы или неизвестная цена; ограничения поиска явны.")
    if plan["deferred"]:
        add("search_deferred", "Research / владелец бюджета", "Разрешить отложенное покрытие поиска",
            f"Вне текущего лимита осталось направлений: {len(plan['deferred'])}. Какие выполнить, какие исключить с основанием?",
            "Согласован охват и ресурс; отложенные направления не представлены как исследованные.")
    for source in state["sources"]:
        if source["access"] == "search_lead":
            add("read_source", "Research", "Прочитать найденный материал", source["title"],
                "Новый источник с фрагментом, датой и статусом чтения; заблокированный доступ сохранён как пробел.", source["id"])
    assessments = []
    for row in comparison(state):
        package, candidate, result = row["package"], row["candidate"], row["evaluation"]
        pid = package["id"]
        if result["stale"]:
            add("reassess", "Research / Brand", "Пересмотреть устаревший пакет", package["name"],
                "Оценки и условия пересмотрены под текущий бриф; прежние решения не перенесены автоматически.", pid, "P0")
        for key in result["missing"]:
            add("criterion_" + key, "Research / Analytics", "Подтвердить: " + CRITERIA[key], package["name"],
                "Основание именно этого пакета, наблюдение, период, источник; пропуск остаётся неизвестным.", pid)
        if candidate["risk"]["status"] != "reviewed":
            add("risk", "Sponsorship / Brand", "Ручная проверка риска", candidate["name"],
                "Факты, обвинения и опровержения разделены; источник, дата и фактическое решение проверяющего.", candidate["id"], "P0")
        if result["followers"]["status"] in ("pending", "fail"):
            add("scale", "Research", "Проверить масштаб и свежесть", candidate["name"],
                "Актуальный счётчик одной платформы; дата, точность, конфликты и покрытие платформ; ЦА подтверждается отдельно.", candidate["id"])
        if package["fee"]["status"] in ("unknown", "estimate"):
            add("offer", "Sponsorship / менеджер партнёра", "Получить условия конкретного пакета", package["name"],
                "Ответ представителя: цена, валюта, период, состав, срок действия, территория, права и доступность.", pid)
        if not package["extra_costs"].get("complete"):
            add("costs", "Finance / Production / Media", "Собрать полные затраты", package["name"],
                "Права, производство, продвижение, логистика, комиссии, налоги и измерение: факт/оценка/неизвестно, валюта и период.", pid)
        if result["economics"]["budget_status"] not in ("within_range", "unknown", "need_full_cost"):
            add("budget", "Finance / Sponsorship", "Разрешить ограничение бюджета", result["economics"]["reason"],
                "Сопоставимые валюта, период, территория и состав затрат; решение владельца сохранено отдельно.", pid)
        review = assessment_review(state, package)
        assessments.append(review)
        if review["status"] != "requires_discussion" or any((v["spread"] or 0) > 0 for v in review["criteria"].values()):
            add("assessments", "Два оценщика / владелец методики", "Проверить рубрику и разногласия", package["name"],
                "Две самостоятельные оценки одной версии и рубрики; причины расхождения; обсуждение не заменяет эмпирическую проверку.", pid)
    measurement = measurement_review(state)
    if measurement["missing"]:
        add("measurement", "Analytics / Brand", "Подготовить план измерения", "Уточнить: " + ", ".join(measurement["missing"]),
            "До запуска согласованы метрика, популяция, окно, источник, доступ, ограничения; для причинного вывода — контроль и дизайн.", priority="P0")
    if state.get("campaign"):
        from .activation import activation_review
        activation = activation_review(state, current)
        for gap in activation["gaps"]:
            add(gap["code"], "Sponsorship / исполнитель активности", gap["title"], gap["question"], gap["acceptance"], gap["entity"], "P0")
    else:
        activation = None
    # Same candidate may appear in several packages. Keep one request per factual gap.
    requests = list({r["id"]: r for r in requests}.values())
    used_calls = sum(s["status"] in ("completed", "failed") for s in state["search_log"])
    used_pages = sum(s.get("pages_read", 0) for s in state["search_log"])
    return {"version": "readiness-0.1", "research_id": state["id"], "title": state["title"], "kind": state["kind"],
            "revision": state["revision"], "as_of": current.isoformat(), "requests": requests,
            "search": {"scheduled": len(scheduled), "deferred": len(plan["deferred"]), "covered": len(scheduled) - len(uncovered), "uncovered": uncovered,
                       "remaining_calls": max(0, state["brief"]["max_search_calls"] - used_calls),
                       "remaining_pages": max(0, state["brief"]["max_pages"] - used_pages),
                       "unknown_cost_entries": sum(s.get("cost") is None for s in state["search_log"])},
            "measurement": measurement, "assessments": assessments, "activation": activation,
            "model_status": "unvalidated", "boundary": "Поручения — черновики: никто не назначен, сообщения не отправлены. Полнота полей не доказывает истинность или ROI."}


def handoff_markdown(report):
    def clean(value):
        return str(value).replace("\r", " ").replace("\n", " ")
    lines = ["# Пакет запросов: " + clean(report["title"]), "",
             f"Исследование {report['research_id']}; revision {report['revision']}; срез {report['as_of']}.",
             "Тип: " + ("СИНТЕТИЧЕСКИЙ ПРИМЕР" if report["kind"] == "synthetic" else "рабочий бриф"), "",
             report["boundary"], "", "Названия отделов обозначают функции. Исполнитель и срок назначаются владельцем.", ""]
    for department in dict.fromkeys(r["department"] for r in report["requests"]):
        lines += ["## " + clean(department), ""]
        for item in report["requests"]:
            if item["department"] != department:
                continue
            lines += [f"### {clean(item['id'])} · {item['priority']} · {clean(item['title'])}", "",
                      "Объект: " + clean(item["entity"]), "", "Запрос: " + clean(item["question"]), "",
                      "Приёмка: " + clean(item["acceptance"]), "", "Ответ: не получен. Исполнитель: не назначен. Срок: не назначен.", ""]
    return "\n".join(lines) + "\n"
