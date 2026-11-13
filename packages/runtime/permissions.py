"""Server-side roles; frontend controls are never an authorization boundary."""
from copy import deepcopy
from .auth import AccessError

RESEARCH = {"update_brief", "add_source", "save_candidate", "save_package", "record_search", "receive_offer",
            "save_task", "task_status", "record_outcome", "save_measurement", "save_pool", "save_entry",
            "acknowledge_task", "template_task"}
REVIEW = RESEARCH | {"select_candidate", "record_assessment", "review_register"}
APPROVE = REVIEW | {"set_weights", "decision", "advance", "start_campaign", "close_case", "waive_entry"}
ALLOWED = {"viewer": set(), "researcher": RESEARCH, "reviewer": REVIEW, "approver": APPROVE, "admin": APPROVE}


def permit(user, roles):
    if user["role"] not in roles:
        raise AccessError()


def action_payload(user, state, action, payload):
    if not isinstance(payload, dict):
        raise ValueError("Данные действия должны быть объектом")
    value = deepcopy(payload)
    role = user["role"]
    if action == "batch":
        operations = value.get("operations")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
            raise ValueError("Пакет: 1–100 операций")
        for op in operations:
            if not isinstance(op, dict) or op.get("action") not in {"add_source", "save_candidate", "save_package", "record_search"}:
                raise AccessError("Недопустимая операция пакетного импорта")
            op["payload"] = action_payload(user, state, op["action"], op.get("payload"))
        return value
    if action not in ALLOWED[role]:
        raise AccessError()
    if action == "save_candidate" and role == "researcher":
        previous = next((c for c in state["candidates"] if c["id"] == value.get("id")), None)
        risk = value.get("risk", {"status": "not_checked", "reason": "", "source_ids": []})
        prior = previous["risk"] if previous else None
        if risk != prior and (risk.get("status") not in ("not_checked", "flagged") or risk.get("human_reviewed")
                              or (prior and prior["status"] == "confirmed_block")):
            raise AccessError("Риск подтверждает проверяющий; исследователь передаёт сигнал")
    if action == "task_status" and value.get("status") in ("accepted", "waived") and role not in ("admin", "approver", "reviewer"):
        raise AccessError("Приёмка требует проверяющего или утверждающего")
    if action == "decision":
        value["decision_maker"] = user["username"]
    if action == "record_assessment":
        value["assessor"] = user["username"]
    return value
