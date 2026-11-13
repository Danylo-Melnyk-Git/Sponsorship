"""Synthetic fixtures. No real brand, offer, representative or campaign."""

from datetime import timedelta

from .models import CRITERIA, today


def seed(service):
    state = service.create({
        "title": "Демонстрация · спортивный бренд в Чили", "kind": "synthetic",
        "request": "Учебный пример всего рабочего процесса. Все кандидаты, цены и показатели вымышлены.",
        "brief": {"company": "Условный спортивный бренд", "product": "Спортивные аксессуары",
                  "goal": "awareness", "primary_metric": "Запоминание бренда; способ опроса ещё уточняется",
                  "audience": "Взрослые жители Чили, интересующиеся спортом — демонстрационная гипотеза",
                  "geo": ["CL"], "budget": {"amount": 200000, "currency": "USD", "months": 12, "scope": "all_in"},
                  "delivery_target": 1000000,
                  "topics": {"direct": ["football", "running"], "audience": ["sport"],
                             "adjacent": [{"term": "music", "reason": "Гипотеза пересечения взрослых аудиторий"}]}},
    })

    def act(action, payload):
        nonlocal state
        state = service.act(state["id"], state["revision"], action, payload, actor="synthetic_demo")

    act("add_source", {"id": "DEMO-SOURCE", "title": "Вымышленный медиакит и история размещений",
                      "reference": "Синтетический материал для проверки логики",
                      "excerpt": "Все показатели, права и цены в этом исследовании придуманы для демонстрации.",
                      "kind": "synthetic", "access": "provided_material", "retrieved_on": today().isoformat()})
    act("advance", {})
    for candidate_id, name, kind, risk in (
        ("demo-a", "Спортивный автор А", "influencer", "reviewed"),
        ("demo-b", "Спортивный автор Б", "influencer", "flagged"),
        ("demo-c", "Условный клуб В", "club", "reviewed"),
    ):
        act("save_candidate", {
            "id": candidate_id, "name": name, "kind": kind, "entity_key": "synthetic:" + candidate_id,
            "queue": "priority", "rationale": "Вымышленный профиль под демонстрационный спортивный бриф",
            "source_ids": ["DEMO-SOURCE"], "metrics": [
                {"platform": "demo", "followers": 250000, "observed_on": today().isoformat(),
                 "precision": "exact", "evidence_ids": ["DEMO-SOURCE"]}] if kind == "influencer" else [],
            "risk": {"status": risk, "reason": "Вымышленный сигнал: нужна ручная проверка" if risk == "flagged" else "",
                     "source_ids": ["DEMO-SOURCE"]},
        })
        act("select_candidate", {"candidate_id": candidate_id, "selected": True, "reason": "Демонстрационный ручной выбор"})
    act("advance", {})
    for candidate_id, values, fee in (("demo-a", (80, 80, 80, 90), 120000),
                                      ("demo-b", (60, 96, 65, 70), 90000),
                                      ("demo-c", (None, 75, 75, 60), None)):
        act("save_package", {
            "id": "pkg-" + candidate_id, "candidate_id": candidate_id, "name": "Годовой контентный пакет",
            "months": 12, "territory": ["CL"], "deliverables": "4 брендированных видео и одна совместная активация",
            "rights": "Использование контента в Чили на год; отчёт после каждой активации",
            "source_ids": ["DEMO-SOURCE"],
            "criteria": {key: {"value": value, "reason": "Синтетическое значение для проверки арифметики",
                               "source_ids": ["DEMO-SOURCE"] if value is not None else []}
                         for key, value in zip(CRITERIA, values)},
            "fee": {"status": "reported" if fee else "unknown", "low": fee, "high": fee,
                    "currency": "USD", "valid_on": today().isoformat(), "basis": "this_package",
                    "source_ids": ["DEMO-SOURCE"]},
            "extra_costs": {"low": 20000, "high": 30000, "complete": True,
                           "reason": "Вымышленные полные расходы на производство, активацию и измерение"},
            "forecast": {"metric": "qualified_impressions", "low": 600000, "base": 800000, "high": 1000000,
                         "basis": "Синтетический сценарий конкретного пакета", "source_ids": ["DEMO-SOURCE"]},
        })
    return state


def complete(service, research_id):
    state = service.store.get(research_id)

    def act(action, payload):
        nonlocal state
        state = service.act(state["id"], state["revision"], action, payload, actor="synthetic_demo")

    act("decision", {"kind": "c_level_continue", "package_id": "pkg-demo-a",
                     "reason": "Синтетический пример разрешения на проработку", "decision_maker": "Условный C-level"})
    act("advance", {})
    act("receive_offer", {"package_id": "pkg-demo-a", "source_ids": ["DEMO-SOURCE"],
                          "representative": "Вымышленный представитель", "note": "Учебное предложение",
                          "fee": {"status": "reported", "low": 115000, "high": 115000, "currency": "USD",
                                  "valid_on": today().isoformat()}})
    offer_id = state["offers"][-1]["id"]
    act("decision", {"kind": "approve_offer", "offer_id": offer_id,
                     "reason": "Демонстрационное утверждение сделки", "decision_maker": "Условный C-level"})
    start, end = (today() - timedelta(days=365)).isoformat(), today().isoformat()
    act("start_campaign", {"offer_id": offer_id, "source_ids": ["DEMO-SOURCE"],
                           "agreement_note": "Вымышленные согласованные обязательства", "start": start, "end": end})
    act("save_task", {"title": "Передать отчёт по четырём видео", "owner": "Условный менеджер",
                      "due": end, "next_action": "Проверить исходную статистику"})
    act("task_status", {"task_id": state["tasks"][-1]["id"], "status": "accepted",
                        "source_ids": ["DEMO-SOURCE"]})
    for metric, value in (("qualified_impressions", 750000), ("full_cost", 140000)):
        act("record_outcome", {"metric": metric, "value": value, "source_ids": ["DEMO-SOURCE"],
                               "start": start, "end": end, "scope": "campaign_total", "currency": "USD"})
    act("advance", {})
    act("close_case", {"recommendation": "change",
                       "lessons": "Синтетический факт ниже базового сценария. Проверить прогноз и механики перед продлением."})
    return state
