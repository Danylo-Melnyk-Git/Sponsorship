"""Checks for evidence readiness and safe local activation planning."""

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import Request, urlopen
import unittest

from packages.domain.activation import activation_review, catalog
from packages.domain.demo import seed
from packages.domain.models import ValidationError, today
from packages.domain.quality import assessment_review, handoff_markdown, measurement_review, readiness
from packages.domain.service import ResearchService, campaign_report
from packages.domain.store import Store
from packages.connectors.legacy import search_plan
from packages.scoring.engine import comparison
from apps.api.server import Server

ROOT = Path(__file__).resolve().parents[1]


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "quality.sqlite3"
        self.service = ResearchService(Store(self.path))
        self.state = seed(self.service)

    def tearDown(self):
        self.temp.cleanup()

    def act(self, action, payload, actor="owner"):
        self.state = self.service.act(self.state["id"], self.state["revision"], action, payload, actor)

    def assessment(self, assessor="Alice", rubric="test-rubric", value=80):
        return {"package_id": "pkg-demo-a", "assessor": assessor, "rubric_version": rubric,
                "independence_note": "Synthetic independent pass", "criteria": {
                    k: {"value": value, "reason": "Synthetic justification", "source_ids": ["DEMO-SOURCE"]}
                    for k in self.state["weights"]}}

    def test_readiness_does_not_change_state_or_revision(self):
        before = deepcopy(self.state)
        report = readiness(self.state)
        self.assertEqual(self.state, before)
        self.assertEqual(report["revision"], before["revision"])
        self.assertEqual(len(report["requests"]), len({r["id"] for r in report["requests"]}))
        self.assertTrue(all(r["status"] == "draft_not_assigned" and r["due"] is None for r in report["requests"]))
        self.assertIn("Уровень результата не выбран", report["measurement"]["claim_scope"])
        self.assertIn("СИНТЕТИЧЕСКИЙ ПРИМЕР", handoff_markdown(report))

    def test_plan_is_not_an_executed_search_and_failed_call_counts_budget(self):
        query_id = search_plan(self.state)["scheduled"][0]["id"]
        self.assertEqual(readiness(self.state)["search"]["covered"], 0)
        self.act("record_search", {"query": "actual query", "provider": "test", "status": "failed",
                                   "plan_query_id": query_id, "pages_read": 0, "cost": None,
                                   "read_attempts": [{"reference": "https://example.test", "status": "blocked", "on": today().isoformat()}]})
        self.assertEqual(readiness(self.state)["search"]["covered"], 0)
        self.assertEqual(readiness(self.state)["search"]["remaining_calls"], 17)
        self.act("record_search", {"query": "actual retry", "provider": "test", "status": "completed", "plan_query_id": query_id})
        self.assertEqual(readiness(self.state)["search"]["covered"], 1)

    def test_invalid_read_log_and_plan_id_roll_back(self):
        for extra in ({"plan_query_id": "invented"}, {"pages_read": 2, "read_attempts": [
                {"reference": "url", "status": "blocked", "on": today().isoformat()}]}):
            with self.assertRaises(ValidationError):
                self.act("record_search", {"query": "q", "provider": "test", "status": "completed", **extra})
        self.assertFalse(self.service.store.get(self.state["id"])["search_log"])

    def test_draft_plan_preserves_unknown_values(self):
        self.act("save_measurement", {"metric": "brand_recall_rate", "unit": "percent"})
        review = measurement_review(self.state)
        self.assertEqual(review["status"], "draft")
        self.assertIsNone(review["plan"]["target"])
        self.assertIsNone(review["roi"]["value"])
        self.assertEqual(review["plan"]["owner"], "")
        self.assertIn("Описательный уровень", review["claim_scope"])
        self.assertIn("не устанавливает причинную добавочность", review["claim_scope"])

    def test_complete_causal_plan_is_for_review_not_validated_roi(self):
        payload = {"metric": "brand_recall_rate", "unit": "percent", "method": "randomized",
                   "start": today().isoformat(), "end": today().isoformat(), "source_ids": ["DEMO-SOURCE"]}
        for key in ("population", "owner", "collection", "data_access", "limitations", "baseline", "control",
                    "assignment", "confounders", "analysis", "uncertainty"):
            payload[key] = "Synthetic draft specification"
        self.act("save_measurement", payload)
        review = measurement_review(self.state)
        self.assertEqual(review["status"], "specified_for_review")
        self.assertEqual(review["empirical_validation"], "not_performed")
        self.assertIsNone(review["roi"]["value"])
        self.assertIn("Сравнительный дизайн заявлен", review["claim_scope"])
        self.assertIn("требует проверки аналитиком", review["claim_scope"])
        self.act("save_measurement", {"metric": "clicks", "unit": "events"})
        self.assertEqual(self.state["measurement_plans"][0]["metric"], "brand_recall_rate")
        self.assertEqual(measurement_review(self.state)["historical_versions"], 2)

    def test_bad_windows_rates_methods_and_sources_rejected(self):
        for extra in ({"target": 101}, {"method": "before_after_causal"}, {"source_ids": ["unknown"]},
                      {"start": "2026-12-31", "end": "2026-01-01"}):
            with self.assertRaises(ValidationError):
                self.act("save_measurement", {"metric": "brand_recall_rate", "unit": "percent", **extra})

    def test_campaign_freezes_measurement_and_later_plan_has_separate_version(self):
        self.act("save_measurement", {"metric": "brand_recall_rate", "unit": "percent"})
        original = deepcopy(measurement_review(self.state)["plan"])
        self.act("decision", {"kind": "c_level_continue", "package_id": "pkg-demo-a",
                              "reason": "Synthetic permission", "decision_maker": "Test"})
        self.act("advance", {})
        self.act("receive_offer", {"package_id": "pkg-demo-a", "source_ids": ["DEMO-SOURCE"],
                                   "representative": "Test", "note": "Synthetic offer",
                                   "fee": {"status": "reported", "low": 115000, "high": 115000,
                                           "currency": "USD", "valid_on": today().isoformat()}})
        offer_id = self.state["offers"][-1]["id"]
        self.act("decision", {"kind": "approve_offer", "offer_id": offer_id,
                              "reason": "Synthetic approval", "decision_maker": "Test"})
        self.act("start_campaign", {"offer_id": offer_id, "source_ids": ["DEMO-SOURCE"],
                                    "agreement_note": "Synthetic agreement", "start": today().isoformat(),
                                    "end": (today()+timedelta(days=30)).isoformat()})
        self.assertEqual(self.state["campaign"]["measurement_baseline"], original)
        self.assertEqual(measurement_review(self.state)["plan"], original)
        self.act("save_measurement", {"metric": "clicks", "unit": "events"})
        self.assertEqual(measurement_review(self.state)["plan"]["campaign_id"], self.state["campaign"]["id"])
        self.assertEqual(measurement_review(self.state)["plan"]["metric"], "clicks")
        self.assertEqual(self.state["campaign"]["measurement_baseline"], original)

    def test_assessments_never_replace_operational_score(self):
        original = comparison(self.state)[0]["evaluation"]["score"]
        self.act("record_assessment", self.assessment())
        self.act("record_assessment", self.assessment("Bob", value=20))
        review = assessment_review(self.state, self.state["packages"][0])
        self.assertEqual(review["criteria"]["audience"]["spread"], 60)
        self.assertEqual(review["assessor_count"], 2)
        self.assertEqual(comparison(self.state)[0]["evaluation"]["score"], original)

    def test_same_assessor_replacement_is_explicit_and_does_not_count_twice(self):
        self.act("record_assessment", self.assessment())
        with self.assertRaises(ValidationError):
            self.act("record_assessment", self.assessment(" alice "))
        payload = self.assessment("ALICE", value=50)
        payload["supersedes"] = self.state["assessments"][0]["id"]
        self.act("record_assessment", payload)
        self.assertEqual(len(self.state["assessments"]), 2)
        self.assertEqual(assessment_review(self.state, self.state["packages"][0])["assessor_count"], 1)

    def test_rubric_mismatch_has_no_numeric_agreement(self):
        self.act("record_assessment", self.assessment())
        self.act("record_assessment", self.assessment("Bob", "another-rubric"))
        review = assessment_review(self.state, self.state["packages"][0])
        self.assertEqual(review["status"], "rubric_mismatch")
        self.assertIsNone(review["criteria"]["audience"]["range"])

    def test_same_assessor_can_assess_another_package_without_replacing_first(self):
        self.act("record_assessment", self.assessment())
        first_id = self.state["assessments"][0]["id"]
        package = deepcopy(self.state["packages"][0])
        package["id"] = "second-package"
        package["name"] = "Another synthetic package"
        self.act("save_package", package)
        self.act("record_assessment", {**self.assessment(), "package_id": "second-package"})
        self.assertEqual(self.state["assessments"][0]["id"], first_id)
        self.assertNotIn("supersedes", self.state["assessments"][1])
        for item in (p for p in self.state["packages"] if p["id"] in ("pkg-demo-a", "second-package")):
            self.assertEqual(assessment_review(self.state, item)["assessor_count"], 1)

    def test_package_and_weight_changes_invalidate_assessments(self):
        self.act("record_assessment", self.assessment())
        package = deepcopy(self.state["packages"][0])
        package["rights"] += " changed"
        self.act("save_package", package)
        self.assertEqual(assessment_review(self.state, self.state["packages"][0])["assessor_count"], 0)
        self.act("record_assessment", self.assessment())
        self.act("set_weights", {"weights": self.state["weights"], "reason": "new priorities version"})
        self.assertEqual(assessment_review(self.state, self.state["packages"][0])["assessor_count"], 0)

    def test_agents_cannot_record_human_assessments_or_measurement_approval(self):
        for action, payload in (("record_assessment", self.assessment()), ("save_measurement", {"metric": "clicks", "unit": "events"})):
            with self.assertRaises(ValidationError):
                self.act(action, payload, "agent:reviewer")

    def test_handoff_cli_is_read_only_and_does_not_overwrite(self):
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        target = Path(self.temp.name) / "handoff.json"
        args = [sys.executable, str(ROOT / "sponsor.py"), "--database", str(self.path), "handoff", self.state["id"], "--format", "json", "--out", str(target)]
        result = subprocess.run(args, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["revision"], self.state["revision"])
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), digest)
        missing = Path(self.temp.name) / "missing.sqlite3"
        args[args.index(str(self.path))] = str(missing)
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)
        self.assertFalse(missing.exists())


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.service = ResearchService(Store(Path(self.temp.name) / "activation.sqlite3"))
        self.payload = {"title": "Synthetic signed partnership", "kind": "synthetic", "brief": {},
                        "sources": [{"id": "contract", "title": "Synthetic agreement", "kind": "synthetic",
                                     "reference": "Test only", "excerpt": "Invented partnership", "retrieved_on": today().isoformat()}],
                        "agreement": {"partner": "Invented club", "currency": "USD", "source_ids": ["contract"], "note": "Synthetic obligations",
                                      "start": (today()-timedelta(days=10)).isoformat(), "end": (today()+timedelta(days=30)).isoformat()}}
        self.state = self.service.create_signed(self.payload)

    def tearDown(self):
        self.temp.cleanup()

    def act(self, action, payload, actor="owner"):
        self.state = self.service.act(self.state["id"], self.state["revision"], action, payload, actor)

    def entry(self, **extra):
        return {"id": "videos", "type": "obligation", "title": "Two videos", "quantity": 2, "unit": "videos", "owner": "Test owner",
                "contract_version": "v1", "clause": "1", "source_ids": ["contract"], "start": self.state["campaign"]["start"], "end": self.state["campaign"]["end"], **extra}

    def task(self, **extra):
        return {"id": "task-a", "title": "Publish", "owner": "Test", "due": today().isoformat(), **extra}

    def test_signed_import_has_no_invented_research_or_approvals(self):
        self.assertEqual(self.state["stage"], "deliver")
        for key in ("candidates", "packages", "decisions", "offers"):
            self.assertEqual(self.state[key], [])
        self.assertIsNone(self.state["campaign"]["baseline"]["evaluation"])
        self.assertEqual(campaign_report(self.state)["metrics"], [])
        self.assertEqual(self.service.view(self.state["id"])["readiness"]["search"]["scheduled"], 0)

    def test_signed_import_requires_material_and_rejects_synthetic_evidence_for_real_case(self):
        for extra in ({"kind": "owner_brief"}, {"sources": []}):
            with self.assertRaises(ValidationError):
                self.service.create_signed({**self.payload, **extra})

    def test_catalog_matches_existing_sixteen_pools_and_fortyeight_templates(self):
        pools = catalog()
        self.assertEqual(len(pools), 16)
        self.assertEqual(sum(len(p["templates"]) for p in pools), 48)
        source = (ROOT / "docs/product/aktivaciya-posle-podpisaniya/puly-i-zadachi.md").read_text(encoding="utf-8-sig")
        self.assertTrue(all(t["title"] in source and t["acceptance"] in source for p in pools for t in p["templates"]))

    def test_overallocation_unknown_quantity_and_outside_rights_window_rejected(self):
        self.act("save_entry", self.entry())
        for extra in ({"allocations": [{"entry_id": "videos", "quantity": 3}]},
                      {"due": (today()+timedelta(days=31)).isoformat(), "allocations": [{"entry_id": "videos", "quantity": 1}]}):
            with self.assertRaises(ValidationError):
                self.act("save_task", self.task(**extra))
        self.act("save_entry", self.entry(quantity=None))
        with self.assertRaises(ValidationError):
            self.act("save_task", self.task(allocations=[{"entry_id": "videos", "quantity": 1}]))

    def test_allocation_reserved_then_accepted_and_waiver_releases_reservation(self):
        self.act("save_entry", self.entry())
        self.act("save_task", self.task(allocations=[{"entry_id": "videos", "quantity": 1}]))
        self.assertEqual(activation_review(self.state)["register"][0]["reserved_quantity"], 1)
        self.act("task_status", {"task_id": "task-a", "status": "accepted", "source_ids": ["contract"]})
        self.act("save_task", self.task(id="task-b", allocations=[{"entry_id": "videos", "quantity": 1}]))
        with self.assertRaises(ValidationError):
            self.act("save_task", self.task(id="task-c", allocations=[{"entry_id": "videos", "quantity": 1}]))
        self.act("task_status", {"task_id": "task-b", "status": "waived", "reason": "Synthetic cancellation"})
        row = activation_review(self.state)["register"][0]
        self.assertEqual((row["accepted_quantity"], row["reserved_quantity"], row["unallocated_quantity"]), (1, 0, 1))
        self.act("waive_entry", {"entry_id": "videos", "reviewer": "Test", "reason": "Documented replacement", "source_ids": ["contract"]})
        self.assertEqual(self.state["register"][0]["waiver"]["remaining_quantity"], 1)

    def test_dependencies_cannot_be_self_referential_cyclic_or_later(self):
        self.act("save_task", self.task())
        self.act("save_task", self.task(id="task-b", depends_on=["task-a"]))
        for payload in (self.task(depends_on=["task-b"]), self.task(depends_on=["task-a"]),
                        self.task(due=(today()+timedelta(days=1)).isoformat())):
            with self.assertRaises(ValidationError):
                self.act("save_task", payload)

    def test_waived_prerequisite_does_not_unlock_dependent_task(self):
        self.act("save_task", self.task())
        self.act("save_task", self.task(id="task-b", depends_on=["task-a"]))
        self.act("task_status", {"task_id": "task-a", "status": "waived", "reason": "Cancelled"})
        with self.assertRaises(ValidationError):
            self.act("task_status", {"task_id": "task-b", "status": "in_progress"})

    def test_actual_acknowledgement_required_and_change_resets_it(self):
        self.act("save_task", self.task(requires_ack=True, acceptance="Synthetic acceptance"))
        with self.assertRaises(ValidationError):
            self.act("task_status", {"task_id": "task-a", "status": "accepted", "source_ids": ["contract"]})
        self.act("acknowledge_task", {"task_id": "task-a", "confirmed_by": "Test", "note": "Synthetic response", "source_ids": ["contract"]})
        self.act("save_task", self.task(owner="Another owner"))
        task = self.state["tasks"][0]
        self.assertNotIn("acknowledgement", task)
        self.assertEqual(task["acceptance"], "Synthetic acceptance")
        self.assertTrue(task["requires_ack"])

    def test_current_register_review_and_close_gate_include_unused_rights(self):
        self.act("save_entry", self.entry(type="right"))
        self.act("review_register", {"reviewer": "Test", "note": "Checked", "source_ids": ["contract"]})
        self.assertTrue(activation_review(self.state)["register_review_current"])
        self.act("save_entry", self.entry(type="right", quantity=3))
        self.assertFalse(activation_review(self.state)["register_review_current"])
        self.act("save_task", self.task())
        self.act("task_status", {"task_id": "task-a", "status": "accepted", "source_ids": ["contract"]})
        self.act("advance", {})
        with self.assertRaises(ValidationError):
            self.act("close_case", {"recommendation": "stop", "lessons": "Synthetic closure"})
        self.act("waive_entry", {"entry_id": "videos", "reviewer": "Test", "reason": "Unused by decision", "source_ids": ["contract"]})
        self.act("review_register", {"reviewer": "Test", "note": "Final version", "source_ids": ["contract"]})
        self.act("close_case", {"recommendation": "stop", "lessons": "Synthetic closure"})
        self.assertIsNotNone(self.state["case"])

    def test_template_requires_applicability_and_does_not_assign_people_or_dates(self):
        with self.assertRaises(ValidationError):
            self.act("template_task", {"template_id": "T01.1", "owner": "Test", "due": today().isoformat()})
        self.act("save_pool", {"pool_id": "P01", "status": "applies", "reviewer": "Test", "reason": "Synthetic applicability", "source_ids": ["contract"]})
        with self.assertRaises(ValidationError):
            self.act("template_task", {"template_id": "T01.1"})
        self.act("template_task", {"template_id": "T01.1", "owner": "Test", "due": today().isoformat()})
        self.assertEqual(self.state["tasks"][0]["pool_id"], "P01")
        self.assertTrue(self.state["tasks"][0]["requires_ack"])

    def test_baseline_plan_and_signed_source_immutability(self):
        self.act("save_measurement", {"metric": "brand_recall_rate", "unit": "percent"})
        first = deepcopy(self.state["measurement_plans"][0])
        self.act("save_measurement", {"metric": "clicks", "unit": "events"})
        self.assertEqual(self.state["measurement_plans"][0], first)
        self.assertIsNone(self.state["campaign"]["measurement_baseline"])
        self.assertIsNone(campaign_report(self.state)["roi"]["value"])

    def test_brand_percentage_outcome_rejects_over_100_and_accepts_zero(self):
        payload = {"metric": "brand_recall_rate", "scope": "partial", "start": self.state["campaign"]["start"], "end": today().isoformat(), "source_ids": ["contract"]}
        with self.assertRaises(ValidationError):
            self.act("record_outcome", {**payload, "value": 101})
        self.act("record_outcome", {**payload, "value": 0})
        self.assertEqual(self.state["outcomes"][-1]["value"], 0)

    def test_http_signed_import_readiness_and_handoff(self):
        server = Server(("127.0.0.1", 0), self.service)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = Request(base + "/api/activation", data=json.dumps(self.payload).encode(), headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=5) as response:
                result = json.load(response)
                self.assertEqual(response.status, 201)
            self.assertIn("activation", result["readiness"])
            with urlopen(base + f"/api/research/{result['id']}/handoff", timeout=5) as response:
                output = response.read().decode("utf-8")
                self.assertIn("СИНТЕТИЧЕСКИЙ ПРИМЕР", output)
                self.assertIn("не назначен", output)
            with urlopen(base + "/api/meta", timeout=5) as response:
                self.assertEqual(len(json.load(response)["activation_catalog"]), 16)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_registrar_changes_require_reconfirmation_for_linked_tasks(self):
        self.act("save_entry", self.entry())
        self.act("save_task", self.task(requires_ack=True, allocations=[{"entry_id": "videos", "quantity": 1}]))
        self.act("acknowledge_task", {"task_id": "task-a", "confirmed_by": "Test", "note": "Response", "source_ids": ["contract"]})
        self.act("save_entry", self.entry(contract_version="v2"))
        self.assertNotIn("acknowledgement", self.state["tasks"][0])


if __name__ == "__main__":
    unittest.main()
