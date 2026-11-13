"""Bounded role contexts and validated imports for Codex-assisted research."""

import json
from pathlib import Path

from .models import require
from packages.connectors.legacy import search_plan

ROOT = Path(__file__).resolve().parents[2]


def configuration():
    return json.loads((ROOT / "agents" / "workflow.json").read_text(encoding="utf-8"))


def role_task(state, role_id):
    role = next((role for role in configuration()["roles"] if role["id"] == role_id), None)
    require(role is not None, "Неизвестная роль")
    require(state["stage"] in role["stages"], "Роль не подходит для текущего этапа")
    selected = [c for c in state["candidates"] if c["selected"]]
    allowed_candidates = state["candidates"] if role_id in ("planner", "discovery", "reviewer") else selected
    packages = [p for p in state["packages"] if p["candidate_id"] in {c["id"] for c in allowed_candidates}]
    task = {
        "schema_version": "1.0", "research_id": state["id"], "expected_revision": state["revision"],
        "brief_version": state["brief_version"], "kind": state["kind"], "role": role,
        "execution": "codex_assisted", "network_executed": False,
        "brief": state["brief"], "candidates": allowed_candidates, "packages": packages,
        "sources": state["sources"], "completed_searches": state["search_log"],
        "human_decisions": state["decisions"], "weekly_obligations": state["tasks"],
        "output_contract": {"research_id": state["id"], "expected_revision": state["revision"],
                            "role": role_id, "operations": [
                                {"action": "one_of_allowed_actions", "payload": "validated_domain_object"}]},
        "boundary": "Это задание для исполнения в Codex. План и экспорт контекста не выполняют сетевые вызовы.",
    }
    if role_id in ("planner", "discovery"):
        task["search_plan"] = search_plan(state)
    if role_id in ("planner", "discovery", "analyst"):
        from packages.strategy.engine import strategy
        task["partner_strategy"] = strategy(state)
    return task


def import_result(service, result):
    require(isinstance(result, dict), "Результат роли должен быть объектом")
    state = service.store.get(result.get("research_id"))
    task = role_task(state, result.get("role"))
    operations = result.get("operations")
    require(isinstance(operations, list) and operations, "Результат роли не содержит операций")
    require(all(op.get("action") in task["role"]["allowed_actions"] for op in operations),
            "Роль пытается выполнить действие за пределами своих полномочий")
    return service.act(state["id"], result.get("expected_revision"), "batch",
                       {"operations": operations}, actor="agent:" + result["role"])
