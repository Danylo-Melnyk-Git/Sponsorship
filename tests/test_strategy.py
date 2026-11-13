"""Search coverage, hypothesis boundaries and independently checkable price limits."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import urlopen
import unittest

from apps.api.server import Server
from packages.connectors.legacy import search_plan
from packages.domain.agents import role_task
from packages.domain.models import validate_brief
from packages.domain.service import ResearchService
from packages.domain.store import Store
from packages.strategy.engine import draft_state, fingerprint, price_conditions, strategy
from packages.strategy import report

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "packages/strategy/examples"


def example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.payload = example("brief-synthetic.json")
        self.state = draft_state(self.payload)
        self.economics = example("economics-synthetic.json")
        self.raw = self.economics["profiles"]["content_series"]

    def test_partial_brief_produces_profile_without_inventing_goal_budget_or_candidates(self):
        result = strategy(draft_state(example("brief-partial.json")))
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["brief"]["goal"], "")
        self.assertIsNone(result["brief"]["budget"]["amount"])
        self.assertTrue(result["missing_brief_fields"])
        self.assertTrue(result["search_plan"]["scheduled"])
        self.assertTrue(all(p["price"]["combined_fee_cap"] is None for p in result["profiles"]))

    def test_three_queries_cover_three_lanes_and_categories(self):
        self.state["brief"]["max_search_calls"] = 3
        rows = search_plan(self.state)["scheduled"]
        self.assertEqual(len({r["lane"] for r in rows}), 3)
        self.assertEqual(len({r["category"] for r in rows}), 3)
        self.assertEqual({r["language"] for r in rows}, {"es"})

    def test_multiple_geographies_get_primary_language_before_secondary(self):
        self.state["brief"]["geo"] = ["CL", "BR"]
        self.state["brief"]["max_search_calls"] = 2
        rows = search_plan(self.state)["scheduled"]
        self.assertEqual({(r["geo"], r["language"]) for r in rows}, {("CL", "es"), ("BR", "pt")})

    def test_explicit_scope_limits_queries_and_profiles(self):
        self.state["brief"]["search_preferences"] = {"categories": ["athletes"], "lanes": ["direct"],
                                                      "languages": ["en"], "formats": ["ambassador"]}
        result = strategy(self.state)
        self.assertEqual([p["id"] for p in result["profiles"]], ["ambassador"])
        rows = result["search_plan"]["scheduled"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["category"], rows[0]["lane"], rows[0]["language"]), ("athletes", "direct", "en"))
        self.assertTrue(result["profiles"][0]["topic_hypotheses"])
        self.assertNotIn("travel", [t["term"] for t in result["profiles"][0]["topic_hypotheses"]])

    def test_unknown_geo_is_exposed_and_does_not_drop_known_geo(self):
        self.state["brief"]["geo"] = ["CL", "ZZ"]
        plan = search_plan(self.state)
        self.assertEqual(plan["unsupported_geographies"], ["ZZ"])
        self.assertEqual({t["geo"] for t in plan["scheduled"]}, {"CL"})

    def test_format_filters_unrelated_categories_and_exposes_impossible_combination(self):
        self.state["brief"]["search_preferences"] = {"formats": ["event_activation"]}
        plan = search_plan(self.state)
        self.assertEqual({t["category"] for t in plan["scheduled"]}, {"events"})
        self.state["brief"]["search_preferences"]["categories"] = ["athletes"]
        result = strategy(self.state)
        self.assertFalse(result["profiles"])
        self.assertFalse(result["search_plan"]["scheduled"])
        self.assertTrue(result["search_plan"]["missing_for_search"])

    def test_missing_topics_or_geo_does_not_invent_queries(self):
        for key, value in (("geo", []), ("topics", {"direct": [], "audience": [], "adjacent": []})):
            with self.subTest(key=key):
                state = deepcopy(self.state)
                state["brief"][key] = value
                plan = search_plan(state)
                self.assertFalse(plan["scheduled"])
                self.assertTrue(plan["missing_for_search"])

    def test_zero_call_or_page_budget_defers_search(self):
        for key in ("max_search_calls", "max_pages"):
            state = deepcopy(self.state)
            state["brief"][key] = 0
            plan = search_plan(state)
            self.assertFalse(plan["scheduled"])
            self.assertTrue(plan["deferred"])

    def test_unavailable_resources_cannot_become_ready(self):
        self.state["brief"]["search_preferences"]["max_profiles"] = 5
        profiles = {p["id"]: p for p in strategy(self.state)["profiles"]}
        self.assertEqual(profiles["ambassador"]["feasibility"], "blocked_by_resources")
        self.assertEqual(profiles["licensed_content"]["feasibility"], "blocked_by_resources")
        self.assertEqual(profiles["event_activation"]["feasibility"], "conditional")
        self.assertEqual(profiles["content_series"]["feasibility"], "resources_declared")

    def test_independent_price_arithmetic_and_other_formats_stay_unknown(self):
        profiles = {p["id"]: p for p in strategy(self.state, self.economics)["profiles"]}
        price = profiles["content_series"]["price"]
        self.assertEqual(price["other_costs"], [40000, 40000])
        self.assertEqual(price["budget_fee_cap"], [140000, 140000])
        self.assertEqual(price["economic_fee_cap"], [60000, 140000])
        self.assertEqual(price["combined_fee_cap"], [60000, 140000])
        self.assertEqual(price["required_outcomes_if_full_budget_spent"], [1800, 2160])
        self.assertIsNone(price["market_price"])
        self.assertIsNone(profiles["event_activation"]["price"]["economic_fee_cap"])

    def test_unknown_cost_and_incomplete_scope_block_calculations(self):
        raw = deepcopy(self.raw)
        raw["other_costs"]["production"].update(status="unknown", low=None, high=None)
        price = price_conditions(self.state["brief"], raw)
        self.assertIsNone(price["economic_fee_cap"])
        self.assertIsNone(price["budget_fee_cap"])
        self.raw["other_cost_scope_complete"] = False
        self.assertIsNone(price_conditions(self.state["brief"], self.raw)["economic_fee_cap"])

    def test_fee_only_is_not_total_spend(self):
        self.state["brief"]["budget"]["scope"] = "fee_only"
        price = price_conditions(self.state["brief"], self.raw)
        self.assertEqual(price["budget_fee_cap"], [180000, 180000])
        self.assertEqual(price["required_outcomes_if_full_budget_spent"], [2200, 2640])

    def test_negative_fee_cap_preserved(self):
        self.raw["incremental_outcomes"].update(low=-10, high=0)
        price = price_conditions(self.state["brief"], self.raw)
        self.assertLess(price["combined_fee_cap"][1], 0)
        self.state["brief"]["budget"]["amount"] = 30000
        self.assertEqual(price_conditions(self.state["brief"], self.raw)["budget_fee_cap"], [-10000, -10000])

    def test_zero_margin_has_no_finite_required_outcomes(self):
        self.raw["margin_per_outcome"].update(low=0, high=0)
        price = price_conditions(self.state["brief"], self.raw)
        self.assertIsNone(price["required_outcomes_if_full_budget_spent"])
        self.assertEqual(price["economic_fee_cap"], [-40000, -40000])

    def test_binding_rejects_changes_in_budget_topics_or_scope(self):
        for key, value in (("goal", "awareness"), ("geo", ["BR"]), ("max_search_calls", 7)):
            state = deepcopy(self.state)
            state["brief"][key] = value
            with self.assertRaisesRegex(ValueError, "другому брифу"):
                strategy(state, self.economics)

    def test_currency_period_geo_and_nonfinite_inputs_rejected(self):
        for key, value in (("currency", "EUR"), ("months", 1), ("months", True), ("geo", ["BR"]), ("target_roi", float("nan"))):
            raw = deepcopy(self.raw)
            raw[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                price_conditions(self.state["brief"], raw)

    def test_profile_economics_cannot_rebind_to_unknown_format(self):
        self.economics["profiles"]["guess"] = self.raw
        with self.assertRaises(ValueError):
            strategy(self.state, self.economics)

    def test_completed_queries_not_repeated_and_failed_need_review(self):
        ids = [t["id"] for t in search_plan(self.state)["scheduled"]]
        self.state["search_log"] = [{"brief_version": 1, "plan_query_id": ids[0], "status": "completed", "pages_read": 2},
                                    {"brief_version": 1, "plan_query_id": ids[1], "status": "failed", "pages_read": 0},
                                    {"brief_version": 0, "plan_query_id": "old", "status": "completed", "pages_read": 1}]
        ex = strategy(self.state)["execution"]
        self.assertEqual(ex["remaining_calls"], 3)
        self.assertEqual(ex["remaining_pages"], 9)
        self.assertEqual(ex["completed_current_plan_cells"], 1)
        self.assertEqual([r["id"] for r in ex["retry_requires_review"]], [ids[1]])
        self.assertTrue(all(r["id"] not in ids[:2] for r in ex["next_queries"]))
        self.assertEqual(len(ex["next_queries"]), 3)

    def test_generation_preserves_state_and_economics(self):
        before = deepcopy((self.state, self.economics))
        result = strategy(self.state, self.economics)
        result["brief"]["company"] = "changed output"
        self.assertEqual((self.state, self.economics), before)

    def test_malformed_preferences_rejected(self):
        for prefs in ({"categories": []}, {"capabilities": {"paid_media": "yes"}}, {"max_profiles": True}, {"languages": ["xx"]}, {"unknown": 1}):
            brief = deepcopy(self.state["brief"])
            brief["search_preferences"] = prefs
            with self.subTest(prefs=prefs), self.assertRaises(ValueError):
                validate_brief(brief)

    def test_report_escapes_untrusted_content_and_retains_evidence(self):
        self.state["title"] = "<script>alert(1)</script>"
        result = strategy(self.state, self.economics)
        html = report.html(result)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn(self.economics["brief_sha256"], html)
        self.assertIn("1800", json.dumps(result))
        self.assertIn("Синтетический", report.markdown(result))

    def test_cli_offline_never_creates_database_or_overwrites_output(self):
        with TemporaryDirectory() as temp:
            db, out = Path(temp) / "absent.sqlite3", Path(temp) / "report.html"
            cmd = [sys.executable, "sponsor.py", "--database", str(db), "strategy", "--brief", str(EXAMPLES / "brief-synthetic.json"),
                   "--economics", str(EXAMPLES / "economics-synthetic.json"), "--format", "html", "--out", str(out)]
            completed = subprocess.run(cmd, cwd=ROOT, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(db.exists())
            original = out.read_bytes()
            self.assertNotEqual(subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode, 0)
            self.assertEqual(out.read_bytes(), original)

    def test_partial_planner_api_and_readonly_cli_keep_revision_and_hash(self):
        with TemporaryDirectory() as temp:
            db = Path(temp) / "test.sqlite3"
            service = ResearchService(Store(db))
            state = service.create(example("brief-partial.json"))
            task = role_task(state, "planner")
            self.assertTrue(task["partner_strategy"]["profiles"])
            query_id = task["search_plan"]["scheduled"][0]["id"]
            state = service.act(state["id"], state["revision"], "record_search", {"query": "synthetic query", "provider": "test", "status": "completed", "plan_query_id": query_id})
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            server = Server(("127.0.0.1", 0), service)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urlopen(base + f'/api/research/{state["id"]}/strategy') as response:
                    html = response.read().decode("utf-8")
                    self.assertIn("/strategy.css", html)
                    self.assertNotIn("<style>", html)
                    self.assertIn("style-src 'self'", response.headers["Content-Security-Policy"])
                with urlopen(base + "/strategy.css") as response:
                    self.assertEqual(response.status, 200)
                cmd = [sys.executable, "sponsor.py", "--database", str(db), "strategy", "--id", state["id"], "--format", "json"]
                completed = subprocess.run(cmd, cwd=ROOT, capture_output=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["execution"]["completed_current_plan_cells"], 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)
            self.assertEqual(service.store.get(state["id"])["revision"], state["revision"])
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
