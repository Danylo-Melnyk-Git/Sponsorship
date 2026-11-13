"""Bridge the existing, tested discovery prototype into the application."""

import importlib.util
import json
from pathlib import Path

from packages.domain.models import brief_missing, require, today

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "research" / "poisk-i-podbor"
spec = importlib.util.spec_from_file_location("discovery_prototype", PROBE / "instrument-poiska.py")
prototype = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prototype)


def search_plan(state):
    from packages.strategy.search import build_plan
    packs = json.loads((PROBE / "pakety-geo.json").read_text(encoding="utf-8-sig"))
    return build_plan(state, prototype, packs)


def probe_payload():
    brief = json.loads((PROBE / "primery" / "brif-chili-demo.json").read_text(encoding="utf-8-sig"))
    return {
        "title": "Публичные источники Чили · технический пример",
        "kind": "synthetic", "request": "Импорт прежнего технического прогона; бренд условный.",
        "brief": {"company": brief["company"]["name"], "product": brief["company"]["product"],
                  "goal": "awareness", "audience": brief["audience"], "geo": brief["geo"],
                  "budget": brief["budget"], "topics": brief["topics"], "primary_metric": "",
                  "restrictions": "\n".join(brief["restrictions"]),
                  **{key: brief["advanced"][key] for key in (
                      "min_followers", "metric_max_age_days", "max_search_calls", "max_pages")}},
    }


def probe_operations():
    corpus = json.loads((PROBE / "primery" / "dose-chili-public.json").read_text(encoding="utf-8-sig"))
    prototype.validate_corpus(corpus, today())
    operations = []
    for source in corpus["evidence"]:
        operations.append({"action": "add_source", "payload": {
            "id": source["id"], "title": source.get("summary") or source["url"], "url": source["url"],
            "excerpt": source["excerpt"], "kind": "public", "access": "page_read",
            "retrieved_on": source["retrieved_on"], "published_on": source.get("published_on"),
            "event_on": source.get("event_on"), "original_metadata": source,
        }})
    for candidate in corpus["candidates"]:
        ids = sorted({sid for claim in candidate["topic_claims"] for sid in claim["evidence_ids"]})
        operations.append({"action": "save_candidate", "payload": {
            "id": candidate["id"], "name": candidate["name"], "kind": candidate["kind"],
            "entity_key": candidate["entity_key"], "official_url": candidate["official_url"],
            "rationale": "Темы из прочитанных источников: " + ", ".join(c["term"] for c in candidate["topic_claims"]),
            "source_ids": ids, "metrics": candidate["metrics"],
            "platform_scan_complete": candidate["platform_scan_complete"], "queue": "needs_data",
            "risk": {"status": candidate["risk"]["status"], "reason": "",
                     "source_ids": candidate["risk"]["evidence_ids"]},
            "original_dossier": candidate,
        }})
    return operations
