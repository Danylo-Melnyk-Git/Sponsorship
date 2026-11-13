"""Behavioural checks for the real local MVP and its six-stage workflow."""

from copy import deepcopy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from apps.api.server import Server
from packages.connectors.legacy import probe_operations, probe_payload, search_plan
from packages.domain.agents import import_result, role_task
from packages.domain.demo import complete, seed
from packages.domain.models import ConflictError, ValidationError, today
from packages.domain.reporting import markdown
from packages.domain.service import ResearchService, campaign_report, weekly
from packages.domain.store import Store
from packages.scoring.engine import comparison, economics, follower_status


class MVPTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.sqlite3")
        self.service = ResearchService(self.store)
        self.state = seed(self.service)

    def tearDown(self):
        self.temp.cleanup()

    def act(self, action, payload, actor="owner"):
        self.state = self.service.act(self.state["id"], self.state["revision"], action, payload, actor)
        return self.state

    def approve_offer(self):
        self.act("decision", {"kind": "c_level_continue", "package_id": "pkg-demo-a",
                             "decision_maker": "Test owner", "reason": "Continue"})
        self.act("advance", {})
        self.act("receive_offer", {"package_id": "pkg-demo-a", "source_ids": ["DEMO-SOURCE"],
                                  "representative": "Synthetic representative", "note": "Synthetic quote",
                                  "fee": {"status": "reported", "low": 100000, "high": 100000,
                                          "currency": "USD", "valid_on": today().isoformat()}})
        offer = self.state["offers"][-1]
        self.act("decision", {"kind": "approve_offer", "offer_id": offer["id"],
                             "decision_maker": "Test owner", "reason": "Approve"})
        return offer

    def start_campaign(self):
        offer = self.approve_offer()
        self.act("start_campaign", {"offer_id": offer["id"], "source_ids": ["DEMO-SOURCE"],
                                   "agreement_note": "Synthetic agreement",
                                   "start": (today() - timedelta(days=365)).isoformat(), "end": today().isoformat()})
        return offer

    def test_six_stage_case_and_export(self):
        result = complete(self.service, self.state["id"])
        self.assertEqual(result["stage"], "report")
        self.assertIsNotNone(result["case"])
        report = campaign_report(result)
        self.assertEqual(report["metrics"][0]["delta"], -50000)
        self.assertEqual(report["actual_full_cost"]["value"], 140000)
        self.assertIsNone(report["roi"]["value"])
        self.assertIn("СИНТЕТИЧЕСКОЕ ДЕМО", markdown(result))

    def test_partial_brief_does_not_invent_period_or_currency(self):
        draft = self.service.create({"title": "Short request", "request": "200 тысяч в месяц или в год",
                                     "brief": {"company": "Brand", "budget": {"amount": 200000}}})
        self.assertIsNone(draft["brief"]["budget"]["months"])
        self.assertEqual(draft["brief"]["budget"]["currency"], "")
        with self.assertRaises(ValidationError):
            self.service.act(draft["id"], draft["revision"], "advance", {})

    def test_owner_licence_statement_is_preserved_without_brand_specific_block(self):
        payload = probe_payload()
        payload["kind"] = "owner_brief"
        payload["brief"]["company"] = "PIN-UP"
        payload["brief"]["licence_note"] = "Owner reports a licence; development does not verify it"
        result = self.service.create(payload)
        result = self.service.act(result["id"], result["revision"], "advance", {})
        self.assertEqual(result["stage"], "screen")
        self.assertEqual(result["brief"]["licence_note"], payload["brief"]["licence_note"])

    def test_bool_and_nonfinite_budget_rejected(self):
        for amount in (True, float("nan"), float("inf")):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.service.create({"title": "Invalid", "brief": {"budget": {"amount": amount}}})

    def test_known_score_reproduces_anchor_example(self):
        row = next(r for r in comparison(self.state) if r["package"]["id"] == "pkg-demo-a")
        self.assertEqual(row["evaluation"]["score"], 82.0)
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["evaluation"]["model_status"], "unvalidated")

    def test_missing_score_has_bounds_and_no_rank(self):
        row = next(r for r in comparison(self.state) if r["package"]["id"] == "pkg-demo-c")
        self.assertIsNone(row["evaluation"]["score"])
        self.assertEqual(row["evaluation"]["interval"], [49.5, 79.5])
        self.assertEqual(row["evaluation"]["coverage"], .7)
        self.assertIsNone(row["rank"])

    def test_risk_cannot_be_cancelled_by_higher_delivery_weight(self):
        self.act("set_weights", {"weights": {"audience": .1, "delivery": .6, "fit": .2, "rights": .1},
                                "reason": "Stress test"})
        rows = comparison(self.state)
        first = next(r for r in rows if r["package"]["id"] == "pkg-demo-a")
        flagged = next(r for r in rows if r["package"]["id"] == "pkg-demo-b")
        self.assertGreater(flagged["evaluation"]["score"], first["evaluation"]["score"])
        self.assertIsNone(flagged["rank"])
        self.assertEqual(first["rank"], 1)

    def test_invalid_weight_sum_rejected(self):
        with self.assertRaises(ValidationError):
            self.act("set_weights", {"weights": {"audience": .4, "delivery": .4, "fit": .4, "rights": .4},
                                     "reason": "Bad sum"})

    def test_score_does_not_depend_on_pool_composition(self):
        before = comparison(self.state)[0]["evaluation"]["score"]
        candidate = deepcopy(self.state["candidates"][0])
        candidate.update(id="new-candidate", entity_key="new-identity")
        self.act("save_candidate", candidate)
        self.assertEqual(comparison(self.state)[0]["evaluation"]["score"], before)

    def test_brief_change_invalidates_score_and_decision(self):
        brief = deepcopy(self.state["brief"])
        brief["budget"]["amount"] = 1000
        self.act("update_brief", {"brief": brief})
        self.assertTrue(all(r["evaluation"]["stale"] for r in comparison(self.state)))
        self.assertTrue(all(r["evaluation"]["score"] is None for r in comparison(self.state)))
        with self.assertRaises(ValidationError):
            self.act("decision", {"kind": "c_level_continue", "package_id": "pkg-demo-a",
                                 "decision_maker": "Owner", "reason": "Old package"})

    def test_stale_package_requires_explicit_reassessment(self):
        package = deepcopy(self.state["packages"][0])
        brief = deepcopy(self.state["brief"])
        brief["audience"] = "Different audience"
        self.act("update_brief", {"brief": brief})
        evaluation = comparison(self.state)[0]["evaluation"]
        self.assertIsNone(evaluation["forecast"])
        self.assertIsNone(evaluation["cost_per_1000_qualified_impressions"])
        self.act("advance", {})
        self.act("advance", {})
        with self.assertRaises(ValidationError):
            self.act("save_package", package)
        package.update(reassess=True, reassessment_reason="Reviewed against new audience")
        self.act("save_package", package)
        self.assertEqual(self.state["packages"][0]["brief_version"], 2)

    def test_unknown_fee_remains_null(self):
        package = self.state["packages"][2]
        result = economics(package, self.state["brief"])
        self.assertIsNone(result["fee_range"])
        self.assertIsNone(result["full_cost_range"])
        self.assertEqual(result["budget_status"], "unknown")

    def test_all_in_cost_requires_known_extras(self):
        package = deepcopy(self.state["packages"][0])
        package["extra_costs"] = {"low": None, "high": None, "complete": False}
        self.assertEqual(economics(package, self.state["brief"])["budget_status"], "need_full_cost")

    def test_different_period_and_currency_are_not_converted(self):
        package = deepcopy(self.state["packages"][0])
        package["months"] = 1
        self.assertEqual(economics(package, self.state["brief"])["budget_status"], "period_mismatch")
        package["fee"]["currency"] = "CLP"
        self.assertEqual(economics(package, self.state["brief"])["budget_status"], "currency_mismatch")

    def test_followers_are_not_summed_and_partial_scan_is_pending(self):
        candidate = deepcopy(self.state["candidates"][0])
        candidate["metrics"][0]["followers"] = 70000
        candidate["metrics"].append({**candidate["metrics"][0], "platform": "another", "followers": 80000})
        self.assertEqual(follower_status(candidate, self.state["brief"], self.state["sources"])["status"], "pending")
        candidate["platform_scan_complete"] = True
        self.assertEqual(follower_status(candidate, self.state["brief"], self.state["sources"])["status"], "fail")

    def test_equal_scores_share_rank_without_artificial_tie_break(self):
        package = deepcopy(self.state["packages"][0])
        package.update(id="same-score-package", name="Same fit, another package")
        self.act("save_package", package)
        ranks = [row["rank"] for row in comparison(self.state) if row["candidate"]["id"] == "demo-a"]
        self.assertEqual(ranks, [1, 1])

    def test_known_over_budget_package_keeps_score_without_eligible_rank(self):
        package = deepcopy(self.state["packages"][0])
        package["fee"].update(low=250000, high=250000)
        self.act("save_package", package)
        row = next(r for r in comparison(self.state) if r["package"]["id"] == package["id"])
        self.assertEqual(row["evaluation"]["score"], 82.0)
        self.assertIn("over_budget", row["evaluation"]["gates"])
        self.assertIsNone(row["rank"])

    def test_latest_hidden_counter_does_not_reuse_old_large_counter(self):
        candidate = deepcopy(self.state["candidates"][0])
        candidate["metrics"][0]["observed_on"] = (today() - timedelta(days=1)).isoformat()
        candidate["metrics"].append({**candidate["metrics"][0], "followers": None,
                                     "precision": "hidden", "observed_on": today().isoformat()})
        self.assertEqual(follower_status(candidate, self.state["brief"], self.state["sources"])["status"], "pending")

    def test_old_counter_and_conflicting_counter_do_not_pass(self):
        candidate = deepcopy(self.state["candidates"][0])
        candidate["metrics"][0]["observed_on"] = (today() - timedelta(days=8)).isoformat()
        self.assertEqual(follower_status(candidate, self.state["brief"], self.state["sources"])["status"], "pending")
        candidate = deepcopy(self.state["candidates"][0])
        candidate["metrics"].append({**candidate["metrics"][0], "followers": 1000})
        self.assertEqual(follower_status(candidate, self.state["brief"], self.state["sources"])["status"], "pending")

    def test_club_does_not_require_influencer_threshold(self):
        self.assertEqual(follower_status(self.state["candidates"][2], self.state["brief"], self.state["sources"])["status"],
                         "not_applicable")

    def test_later_observation_resolves_previous_day_counter_conflict(self):
        candidate = deepcopy(self.state["candidates"][0])
        first = {**candidate["metrics"][0], "observed_on": (today() - timedelta(days=1)).isoformat()}
        candidate["metrics"] = [first, {**first, "followers": 1000},
                                {**first, "observed_on": today().isoformat(), "followers": 120000}]
        self.assertEqual(follower_status(candidate, self.state["brief"], self.state["sources"])["status"], "pass")

    def test_source_snippet_cannot_support_a_number(self):
        self.act("add_source", {"id": "LEAD", "title": "Search lead", "reference": "Search snippet",
                               "excerpt": "Unopened search result", "kind": "synthetic", "access": "search_lead",
                               "retrieved_on": today().isoformat()})
        package = deepcopy(self.state["packages"][0])
        package["criteria"]["audience"]["source_ids"] = ["LEAD"]
        with self.assertRaises(ValidationError):
            self.act("save_package", package)

    def test_synthetic_source_cannot_enter_real_research(self):
        state = self.service.create({"title": "Real", "brief": {}})
        with self.assertRaises(ValidationError):
            self.service.act(state["id"], state["revision"], "add_source", self.state["sources"][0])

    def test_unknown_source_and_script_url_rejected(self):
        package = deepcopy(self.state["packages"][0])
        package["criteria"]["fit"]["source_ids"] = ["UNKNOWN"]
        with self.assertRaises(ValidationError):
            self.act("save_package", package)
        source = deepcopy(self.state["sources"][0])
        source.update(id="BADURL", url="javascript:alert(1)")
        with self.assertRaises(ValidationError):
            self.act("add_source", source)

    def test_duplicate_identity_preserves_original_candidate(self):
        candidate = deepcopy(self.state["candidates"][0])
        candidate["id"] = "another-id"
        with self.assertRaises(ValidationError):
            self.act("save_candidate", candidate)
        self.assertEqual(len(self.store.get(self.state["id"])["candidates"]), 3)

    def test_atomic_import_rolls_back_first_operation_on_later_failure(self):
        source = deepcopy(self.state["sources"][0])
        source["id"] = "NEW-SOURCE"
        revision = self.state["revision"]
        with self.assertRaises(ValidationError):
            self.act("batch", {"operations": [{"action": "add_source", "payload": source},
                                               {"action": "save_candidate", "payload": {"name": "Bad"}}]})
        persisted = self.store.get(self.state["id"])
        self.assertEqual(persisted["revision"], revision)
        self.assertNotIn("NEW-SOURCE", {s["id"] for s in persisted["sources"]})

    def test_revision_conflict_cannot_overwrite_another_session(self):
        stale = self.state["revision"]
        self.act("set_weights", {"weights": {"audience": .25, "delivery": .25, "fit": .25, "rights": .25},
                                "reason": "Another session"})
        with self.assertRaises(ConflictError):
            self.service.act(self.state["id"], stale, "advance", {})
        self.assertEqual(self.store.get(self.state["id"])["weights"]["audience"], .25)

    def test_snapshots_remain_after_reopening_database(self):
        first = self.store.snapshot(self.state["id"], 1)
        reopened = Store(self.store.path)
        self.assertEqual(reopened.snapshot(self.state["id"], 1), first)
        self.assertFalse(first["candidates"])
        self.assertEqual(len(reopened.get(self.state["id"])["candidates"]), 3)

    def test_agent_cannot_make_human_decision_or_confirm_risk(self):
        with self.assertRaises(ValidationError):
            self.act("decision", {"kind": "c_level_continue"}, actor="agent:analyst")
        candidate = deepcopy(self.state["candidates"][0])
        candidate["risk"] = {"status": "confirmed_block", "reason": "Critical",
                             "source_ids": ["DEMO-SOURCE"], "human_reviewed": True}
        with self.assertRaises(ValidationError):
            self.act("save_candidate", candidate, actor="agent:reviewer")

    def test_role_result_permissions_and_revision_are_checked(self):
        task = role_task(self.state, "dossier")
        self.assertFalse(task["network_executed"])
        with self.assertRaises(ValidationError):
            import_result(self.service, {"research_id": self.state["id"], "expected_revision": self.state["revision"],
                                         "role": "dossier", "operations": [{"action": "decision", "payload": {}}]})

    def test_agent_cannot_clear_human_block_or_mark_unchecked_risk_reviewed(self):
        candidate = deepcopy(self.state["candidates"][1])
        candidate["risk"]["status"] = "reviewed"
        with self.assertRaises(ValidationError):
            self.act("save_candidate", candidate, actor="agent:dossier")
        candidate["risk"] = {"status": "confirmed_block", "reason": "Human finding",
                             "source_ids": ["DEMO-SOURCE"], "human_reviewed": True}
        self.act("save_candidate", candidate)
        unchanged = deepcopy(self.state["candidates"][1])
        unchanged["rationale"] = "Additional sourced material"
        self.act("save_candidate", unchanged, actor="agent:dossier")
        unchanged["risk"] = {"status": "not_checked", "reason": "", "source_ids": []}
        with self.assertRaises(ValidationError):
            self.act("save_candidate", unchanged, actor="agent:dossier")

    def test_changed_package_invalidates_permission_to_approach(self):
        self.act("decision", {"kind": "c_level_continue", "package_id": "pkg-demo-a",
                             "decision_maker": "Owner", "reason": "Continue"})
        package = deepcopy(self.state["packages"][0])
        package["rights"] = "Different rights"
        self.act("save_package", package)
        with self.assertRaises(ValidationError):
            self.act("advance", {})
        self.act("decision", {"kind": "c_level_continue", "package_id": "pkg-demo-a",
                             "decision_maker": "Owner", "reason": "Approve new version"})
        self.act("advance", {})
        self.assertEqual(self.state["stage"], "negotiate")

    def test_changed_priorities_invalidate_offer_approval_before_campaign(self):
        offer = self.approve_offer()
        self.act("set_weights", {"weights": {"audience": .25, "delivery": .25, "fit": .25, "rights": .25},
                                 "reason": "Changed priorities"})
        with self.assertRaises(ValidationError):
            self.act("start_campaign", {"offer_id": offer["id"], "start": today().isoformat(), "end": today().isoformat(),
                                        "agreement_note": "Test", "source_ids": ["DEMO-SOURCE"]})

    def test_changed_offered_package_requires_new_approval(self):
        offer = self.approve_offer()
        package = deepcopy(self.state["packages"][-1])
        package["rights"] = "Changed usage rights"
        self.act("save_package", package)
        with self.assertRaises(ValidationError):
            self.act("start_campaign", {"offer_id": offer["id"], "start": today().isoformat(), "end": today().isoformat(),
                                        "agreement_note": "Test", "source_ids": ["DEMO-SOURCE"]})

    def test_received_price_cannot_be_overwritten_as_an_estimate(self):
        self.approve_offer()
        package = deepcopy(self.state["packages"][-1])
        package["fee"]["low"] = 50000
        with self.assertRaises(ValidationError):
            self.act("save_package", package)
        self.assertEqual(self.store.get(self.state["id"])["offers"][-1]["fee"]["low"], 100000)

    def test_received_rights_change_requires_fresh_score(self):
        self.act("decision", {"kind": "c_level_continue", "package_id": "pkg-demo-a",
                             "decision_maker": "Owner", "reason": "Continue"})
        self.act("advance", {})
        original = deepcopy(self.state["packages"][0])
        self.act("receive_offer", {"package_id": original["id"], "source_ids": ["DEMO-SOURCE"],
                                  "representative": "Synthetic", "note": "Changed rights", "rights": "No content reuse",
                                  "fee": {"status": "reported", "low": 100000, "high": 100000,
                                          "currency": "USD", "valid_on": today().isoformat()}})
        offered = self.state["packages"][-1]
        self.assertIsNone(offered["forecast"])
        self.assertTrue(all(entry["value"] is None for entry in offered["criteria"].values()))
        self.assertEqual(self.state["packages"][0], original)

    def test_campaign_requires_an_approved_offer(self):
        with self.assertRaises(ValidationError):
            self.act("start_campaign", {"offer_id": "not-approved"})

    def test_campaign_baseline_does_not_change_with_new_brief_or_weights(self):
        self.start_campaign()
        baseline = deepcopy(self.state["campaign"]["baseline"])
        brief = deepcopy(self.state["brief"])
        brief["budget"]["amount"] = 999
        self.act("update_brief", {"brief": brief})
        self.act("set_weights", {"weights": {"audience": .25, "delivery": .25, "fit": .25, "rights": .25},
                                "reason": "Future planning"})
        self.assertEqual(self.state["campaign"]["baseline"], baseline)

    def test_task_acceptance_requires_proof_and_waiver_requires_reason(self):
        self.start_campaign()
        self.act("save_task", {"title": "Deliver", "owner": "Manager", "due": today().isoformat()})
        task_id = self.state["tasks"][-1]["id"]
        with self.assertRaises(ValidationError):
            self.act("task_status", {"task_id": task_id, "status": "accepted", "source_ids": []})
        with self.assertRaises(ValidationError):
            self.act("task_status", {"task_id": task_id, "status": "waived", "reason": ""})

    def test_weekly_report_does_not_mark_accepted_tasks_overdue(self):
        self.start_campaign()
        self.act("save_task", {"title": "Past", "owner": "Manager",
                              "due": (today() - timedelta(days=1)).isoformat()})
        self.assertEqual(len(weekly(self.state)["overdue"]), 1)
        self.act("task_status", {"task_id": self.state["tasks"][-1]["id"], "status": "accepted",
                                "source_ids": ["DEMO-SOURCE"]})
        self.assertEqual(len(weekly(self.state)["overdue"]), 0)

    def test_partial_result_is_not_compared_to_full_campaign(self):
        self.start_campaign()
        self.act("record_outcome", {"metric": "qualified_impressions", "value": 100, "source_ids": ["DEMO-SOURCE"],
                                    "start": self.state["campaign"]["start"], "end": today().isoformat(), "scope": "partial"})
        report = campaign_report(self.state)
        self.assertIsNone(report["metrics"][0]["actual"])
        self.assertEqual(len(report["partial_observations"]), 1)

    def test_zero_actual_is_real_zero_without_percentage_division(self):
        self.start_campaign()
        self.act("record_outcome", {"metric": "qualified_impressions", "value": 0, "source_ids": ["DEMO-SOURCE"],
                                    "start": self.state["campaign"]["start"], "end": self.state["campaign"]["end"],
                                    "scope": "campaign_total"})
        row = campaign_report(self.state)["metrics"][0]
        self.assertEqual(row["actual"]["value"], 0)
        self.assertIsNone(row["absolute_percentage_error"])
        self.assertIsNone(campaign_report(self.state)["roi"]["value"])

    def test_close_requires_accepted_or_explicitly_waived_obligations(self):
        self.start_campaign()
        self.act("save_task", {"title": "Pending", "owner": "Manager", "due": today().isoformat()})
        self.act("advance", {})
        with self.assertRaises(ValidationError):
            self.act("close_case", {"recommendation": "renew", "lessons": "Unfinished"})

    def test_closed_case_is_read_only(self):
        result = complete(self.service, self.state["id"])
        with self.assertRaises(ValidationError):
            self.service.act(result["id"], result["revision"], "set_weights",
                             {"weights": result["weights"], "reason": "Overwrite case"})

    def test_legacy_public_probe_import_retains_sources_and_unknown_costs(self):
        state = self.service.create(probe_payload())
        state = self.service.act(state["id"], state["revision"], "batch", {"operations": probe_operations()})
        self.assertEqual(len(state["candidates"]), 7)
        self.assertTrue(all(s["kind"] == "public" for s in state["sources"]))
        self.assertEqual(state["packages"], [])
        self.assertEqual(state["candidates"][0]["original_dossier"]["opportunities"][0]["cost"]["status"], "unknown")

    def test_search_plan_is_explicitly_not_executed(self):
        plan = search_plan(self.state)
        self.assertFalse(plan["network_executed"])
        self.assertTrue(plan["scheduled"])
        self.assertEqual(self.state["search_log"], [])

    def test_search_limit_and_unknown_provider_cost(self):
        brief = deepcopy(self.state["brief"])
        brief["max_search_calls"] = 1
        self.act("update_brief", {"brief": brief})
        self.act("record_search", {"query": "football Chile", "provider": "test", "status": "completed", "pages_read": 1})
        self.assertIsNone(self.state["search_log"][0]["cost"])
        with self.assertRaises(ValidationError):
            self.act("record_search", {"query": "another", "provider": "test", "status": "completed", "pages_read": 1})


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.service = ResearchService(Store(Path(self.temp.name) / "http.sqlite3"))
        self.server = Server(("127.0.0.1", 0), self.service)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_real_http_create_edit_conflict_and_export(self):
        status, _, data = self.request("/api/research", {"title": "HTTP", "brief": {}})
        self.assertEqual(status, 201)
        state = json.loads(data)
        self.assertEqual(self.request(f"/api/research/{state['id']}")[0], 200)
        body = {"revision": state["revision"], "action": "add_source", "payload": {
            "title": "Provided", "reference": "Memo", "excerpt": "Owner supplied",
            "retrieved_on": today().isoformat()}}
        self.assertEqual(self.request(f"/api/research/{state['id']}/actions", body)[0], 200)
        self.assertEqual(self.request(f"/api/research/{state['id']}/actions", body)[0], 409)
        status, headers, data = self.request(f"/api/research/{state['id']}/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("HTTP", data.decode())
        status, headers, data = self.request(f"/api/research/{state['id']}/export.pdf")
        if importlib.util.find_spec("reportlab"):
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "application/pdf")
            self.assertIn("attachment", headers["Content-Disposition"])
            self.assertTrue(data.startswith(b"%PDF-"))
        else:
            self.assertEqual(status, 503)

    def test_assets_private_paths_and_security_headers(self):
        for path in ("/", "/app.js", "/styles.css"):
            status, headers, _ = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path in ("/data/private/workspace.sqlite3", "/../AGENTS.md", "/api/research/unknown"):
            self.assertEqual(self.request(path)[0], 404)

    def test_foreign_origin_and_rebinding_host_rejected(self):
        self.assertEqual(self.request("/api/research", {}, {"Origin": "https://example.com"})[0], 400)
        self.assertEqual(self.request("/api/meta", headers={"Host": "attacker.example"})[0], 400)

    def test_demo_api_and_derived_comparison(self):
        status, _, data = self.request("/api/demo", {})
        self.assertEqual(status, 201)
        state = json.loads(data)
        self.assertEqual(state["kind"], "synthetic")
        self.assertEqual(state["comparison"][0]["evaluation"]["score"], 82.0)

    def test_public_binding_rejected(self):
        with self.assertRaises(ValidationError):
            Server(("0.0.0.0", 0), self.service)


if __name__ == "__main__":
    unittest.main()
