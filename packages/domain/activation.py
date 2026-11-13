"""Local rights and obligations register; no bookings or external notifications."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from .models import identifier, iso_date, number, require, text, today, utcnow
from .quality import evidence


def catalog():
    return json.loads((Path(__file__).with_name("activation_catalog.json")).read_text(encoding="utf-8"))


def save_pool(state, payload, actor):
    require(state.get("campaign"), "Сначала начните кампанию")
    pool_id = payload.get("pool_id")
    require(pool_id in {p["id"] for p in catalog()}, "Неизвестный пул")
    status = payload.get("status")
    require(status in ("applies", "not_applicable", "needs_clarification"), "Неизвестная применимость")
    item = {"pool_id": pool_id, "status": status, "reason": text(payload.get("reason"), "Основание применимости"),
            "reviewer": text(payload.get("reviewer"), "Проверяющий"),
            "source_ids": evidence(payload.get("source_ids", []), state, required=True), "at": utcnow(), "actor": actor}
    state.setdefault("pool_reviews", []).append(item)


def allocations(state, entry_id):
    return [(t, a["quantity"]) for t in state["tasks"] if t["status"] != "waived"
            for a in t.get("allocations", []) if a["entry_id"] == entry_id]


def save_entry(state, payload, actor):
    require(state.get("campaign"), "Сначала начните кампанию")
    item = {"id": text(payload.get("id") or identifier("entry"), "ID", limit=100)}
    previous = next((e for e in state.get("register", []) if e["id"] == item["id"]), None)
    linked = allocations(state, item["id"])
    if previous:
        require(not previous.get("waiver"), "Снятый пункт сохраняется; добавьте новую версию отдельной записью")
        require(not any(t["status"] == "accepted" for t, _ in linked), "Пункт с принятым исполнением сохраняется; добавьте новую запись с основанием изменения")
    require(payload.get("type") in ("right", "obligation"), "Укажите право или обязательство")
    item["type"] = payload["type"]
    for key in ("title", "unit", "contract_version", "clause", "owner"):
        item[key] = text(payload.get(key), key)
    item["quantity"] = number(payload.get("quantity"), "Объём", low=0.000001, optional=True)
    item["start"] = iso_date(payload.get("start"), "Начало права")
    item["end"] = iso_date(payload.get("end"), "Окончание права")
    require(item["start"] <= item["end"], "Период права перепутан")
    item["request_by"] = iso_date(payload.get("request_by"), "Срок запроса", optional=True)
    require(not item["request_by"] or item["request_by"] <= item["end"], "Запрос должен быть до окончания права")
    item["source_ids"] = evidence(payload.get("source_ids", []), state, required=True)
    if linked:
        require(item["quantity"] is not None and sum(q for _, q in linked) <= item["quantity"], "Новый объём меньше распределённого")
        require(all(item["start"] <= t["due"] <= item["end"] for t, _ in linked), "Задача выходит за новый период права")
    item.update(version=previous.get("version", 1) + 1 if previous else 1, updated_at=utcnow(), updated_by=actor)
    items = state.setdefault("register", [])
    if previous:
        items[items.index(previous)] = item
        for task, _ in linked:
            task.pop("acknowledgement", None)
    else:
        items.append(item)


def review_register(state, payload, actor):
    require(state.get("campaign") and state.get("register"), "Сначала заполните реестр")
    state.setdefault("register_reviews", []).append({
        "reviewer": text(payload.get("reviewer"), "Кто сверил полноту"),
        "note": text(payload.get("note"), "Что сверено и какие исключения остались"),
        "source_ids": evidence(payload.get("source_ids", []), state, required=True),
        "versions": {e["id"]: e["version"] for e in state["register"]}, "at": utcnow(), "actor": actor})


def waive_entry(state, payload, actor):
    entry = next((e for e in state.get("register", []) if e["id"] == payload.get("entry_id")), None)
    require(entry is not None and not entry.get("waiver"), "Пункт не найден или уже снят")
    linked = allocations(state, entry["id"])
    require(not any(t["status"] != "accepted" for t, _ in linked), "Сначала явно разрешите связанные задачи")
    entry["waiver"] = {"reason": text(payload.get("reason"), "Основание снятия пункта"),
                       "reviewer": text(payload.get("reviewer"), "Кто принял решение"),
                       "source_ids": evidence(payload.get("source_ids", []), state, required=True),
                       "actor": actor, "at": utcnow()}
    entry["waiver"]["remaining_quantity"] = entry["quantity"] - sum(q for _, q in linked) if entry["quantity"] is not None else None
    entry["version"] += 1


def validate_task_links(state, item):
    dependencies = item.setdefault("depends_on", [])
    require(isinstance(dependencies, list) and all(isinstance(v, str) for v in dependencies)
            and len(set(dependencies)) == len(dependencies), "Зависимости: уникальные ID задач")
    by_id = {t["id"]: t for t in state["tasks"] if t["id"] != item["id"]}
    require(set(dependencies) <= set(by_id) and item["id"] not in dependencies, "Неизвестная или собственная зависимость")
    require(all(by_id[d]["due"] <= item["due"] for d in dependencies), "Предшественник назначен позже зависимой задачи")
    graph = {key: t.get("depends_on", []) for key, t in by_id.items()} | {item["id"]: dependencies}
    visiting, visited = set(), set()

    def visit(key):
        require(key not in visiting, "Цикл зависимостей задач")
        if key in visited:
            return
        visiting.add(key)
        for parent in graph[key]:
            visit(parent)
        visiting.remove(key)
        visited.add(key)
    for key in graph:
        visit(key)
    require(all(item["due"] <= t["due"] for t in by_id.values() if item["id"] in t.get("depends_on", [])),
            "Новый срок предшественника позже зависимой задачи")
    item["pool_id"] = text(item.get("pool_id", ""), "Пул", required=False)
    require(not item["pool_id"] or item["pool_id"] in {p["id"] for p in catalog()}, "Неизвестный пул")
    item["acceptance"] = text(item.get("acceptance", ""), "Критерий приёмки", required=False)
    require(isinstance(item.setdefault("requires_ack", False), bool), "Неверный признак подтверждения назначения")
    values = item.setdefault("allocations", [])
    require(isinstance(values, list) and all(isinstance(a, dict) for a in values), "Распределение прав должно быть списком")
    ids = [a.get("entry_id") for a in values]
    require(all(isinstance(v, str) for v in ids) and len(set(ids)) == len(ids), "Неверные или повторные пункты реестра")
    entries = {e["id"]: e for e in state.get("register", [])}
    for allocation in values:
        eid = allocation["entry_id"]
        require(eid in entries and not entries[eid].get("waiver"), "Право неизвестно или снято")
        amount = number(allocation.get("quantity"), "Объём задачи", low=0.000001)
        entry = entries[eid]
        require(entry["quantity"] is not None, "Сначала уточните доступный объём права")
        reserved = sum(q for task, q in allocations(state, eid) if task["id"] != item["id"])
        require(reserved + amount <= entry["quantity"] + 1e-8, "Объём распределён сверх доступного права")
        require(entry["start"] <= item["due"] <= entry["end"], "Срок задачи выходит за период права")


def task_blockers(state, task):
    by_id = {t["id"]: t for t in state["tasks"]}
    blockers = ["Не принят результат: " + by_id[d]["title"] for d in task.get("depends_on", []) if by_id[d]["status"] != "accepted"]
    if task.get("requires_ack") and not task.get("acknowledgement"):
        blockers.append("Исполнитель не подтвердил получение задачи")
    return blockers


def acknowledge_task(state, payload, actor):
    task = next((t for t in state["tasks"] if t["id"] == payload.get("task_id")), None)
    require(task is not None and task["status"] not in ("accepted", "waived"), "Задача не найдена или закрыта")
    task["acknowledgement"] = {"confirmed_by": text(payload.get("confirmed_by"), "Кто подтвердил назначение"),
                               "note": text(payload.get("note"), "Фактическое подтверждение"),
                               "source_ids": evidence(payload.get("source_ids", []), state, required=True),
                               "task_version": task.get("version", 1), "actor": actor, "at": utcnow()}


def activation_review(state, as_of=None):
    current = (as_of or today()).isoformat()
    gaps, rows = [], []

    def gap(code, entity, title, question, acceptance):
        gaps.append(dict(code=code, entity=entity, title=title, question=question, acceptance=acceptance))
    for entry in state.get("register", []):
        linked = allocations(state, entry["id"])
        used = sum(q for task, q in linked if task["status"] == "accepted")
        reserved = sum(q for task, q in linked if task["status"] != "accepted")
        remaining = max(0, round(entry["quantity"] - used - reserved, 8)) if entry["quantity"] is not None else None
        rows.append({**deepcopy(entry), "accepted_quantity": used, "reserved_quantity": reserved,
                     "unallocated_quantity": remaining, "expired": entry["end"] < current,
                     "request_overdue": bool(entry["request_by"] and entry["request_by"] < current and remaining),
                     "task_ids": [t["id"] for t, _ in linked]})
        if not entry.get("waiver") and (entry["quantity"] is None or remaining):
            gap("uncovered_entry", entry["id"], "Уточнить или распределить пункт реестра", entry["title"],
                "Объём известен и привязан к задачам либо есть документированное решение об остатке.")
        if entry["end"] < current and not entry.get("waiver") and (entry["quantity"] is None or used < entry["quantity"]):
            gap("expired_entry", entry["id"], "Разобрать истёкшее право/обязательство", entry["title"],
                "Подтверждены исполнение, нарушение, замена или снятие; истечение не считается исполнением.")
    versions = {e["id"]: e["version"] for e in state.get("register", [])}
    review = state.get("register_reviews", [])[-1] if state.get("register_reviews") else None
    complete = bool(versions and review and review["versions"] == versions)
    if not complete:
        gap("register_review", "campaign", "Сверить полноту реестра с договором", "Есть ли все обязательства и приложения текущей версии?",
            "Человек подтвердил охват конкретных источников и версий пунктов; неизвестные условия перечислены.")
    latest_pools = {p["pool_id"]: p for p in state.get("pool_reviews", [])}
    pools = []
    for pool in catalog():
        item = latest_pools.get(pool["id"])
        pools.append({**pool, "review": deepcopy(item)})
        if not item or item["status"] == "needs_clarification":
            gap("pool_review", pool["id"], "Проверить применимость пула", pool["title"],
                "Применяется / не применяется с причиной, проверяющий и материал. Люди и сроки не наследуются из архива.")
    for task in state["tasks"]:
        if task["status"] in ("accepted", "waived"):
            continue
        blockers = task_blockers(state, task)
        if blockers:
            gap("task_dependency", task["id"], "Разрешить зависимости и назначение", "; ".join(blockers),
                "Подтверждены назначение и приёмка предшественников либо согласовано изменение задач с историей.")
    return {"register": rows, "register_review_current": complete, "pools": pools, "gaps": gaps,
            "task_blockers": {t["id"]: task_blockers(state, t) for t in state["tasks"] if t["status"] not in ("accepted", "waived")},
            "boundary": "Распределение означает внутренний план. Право, бронирование и фактическое использование подтверждают люди."}
