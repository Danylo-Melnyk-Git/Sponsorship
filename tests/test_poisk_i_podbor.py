"""Проверки существенных границ отбора на явно синтетических данных."""
import copy
import importlib.util
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "research/poisk-i-podbor"
spec = importlib.util.spec_from_file_location("poisk", MODULE / "instrument-poiska.py")
poisk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poisk)
TODAY = date(2026, 9, 30)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.brief = poisk.read_json(MODULE / "primery/brif-chili-demo.json")
        self.packs = poisk.read_json(MODULE / "pakety-geo.json")
        self.corpus = poisk.read_json(MODULE / "primery/dose-chili-public.json")
        self.candidate = copy.deepcopy(self.corpus["candidates"][2])
        self.candidate["platform_scan_complete"] = True
        self.s = poisk.settings(self.brief)

    def metric(self, count, platform="youtube", observed="2026-09-30", **extra):
        return {"platform": platform, "account_url": f"https://example.org/{platform}/synthetic",
                "followers": count, "precision": "exact", "observed_on": observed,
                "evidence_ids": ["E-ASTRO"], **extra}

    def gate(self, *metrics):
        self.candidate["metrics"] = list(metrics)
        return poisk.follower_gate(self.candidate, self.s, TODAY)["status"]

    def cost(self, **extra):
        return {"status": "estimate", "low": 50000, "high": 80000,
                "currency": "USD", "months": 12, "cost_basis": "all_in",
                "scope_match": True, "evidence_ids": ["E-ASTRO"],
                "valid_on": "2026-09-30", "valid_until": "2026-10-01",
                "source_price_kind": "creator_activation",
                "derivation": "Синтетический диапазон для проверки логики, не рыночная оценка",
                **extra}

    def budget(self, **extra):
        o = copy.deepcopy(self.candidate["opportunities"][0])
        o["cost"] = self.cost(**extra)
        return poisk.budget_result(self.candidate, o, self.brief, TODAY)

    def test_does_not_sum_two_platforms(self):
        self.assertEqual(self.gate(self.metric(60000), self.metric(60000, "instagram")), "fail")

    def test_exact_threshold_on_one_platform_passes(self):
        self.assertEqual(self.gate(self.metric(100000)), "pass")

    def test_other_small_platform_does_not_block(self):
        self.assertEqual(self.gate(self.metric(1000), self.metric(120000, "instagram")), "pass")

    def test_unknown_is_pending(self):
        self.assertEqual(self.gate(), "pending")

    def test_stale_large_counter_is_pending(self):
        self.assertEqual(self.gate(self.metric(900000, observed="2026-09-10")), "pending")

    def test_partial_scan_cannot_exclude(self):
        self.candidate["platform_scan_complete"] = False
        self.assertEqual(self.gate(self.metric(50000)), "pending")

    def test_rounded_boundary_is_pending(self):
        self.assertEqual(self.gate(self.metric(100000, precision="rounded")), "pending")

    def test_rounded_bounds_allow_decision(self):
        self.assertEqual(self.gate(self.metric(100000, precision="rounded", lower_bound=100000, upper_bound=100999)), "pass")

    def test_latest_observation_replaces_older_threshold_pass(self):
        self.assertEqual(self.gate(self.metric(110000, observed="2026-09-28"),
                                   self.metric(90000, observed="2026-09-29")), "fail")

    def test_conflicting_same_day_counters_are_pending(self):
        self.assertEqual(self.gate(self.metric(110000), self.metric(90000)), "pending")

    def test_new_hidden_counter_does_not_use_older_large_count(self):
        self.assertEqual(self.gate(self.metric(110000, observed="2026-09-29"),
                                   self.metric(None)), "pending")

    def test_override_is_persisted_and_applied(self):
        self.s = poisk.settings(self.brief, 50000)
        self.assertEqual(self.gate(self.metric(60000)), "pass")

    def test_club_is_not_filtered_by_followers(self):
        self.candidate["kind"] = "club"
        self.assertEqual(self.gate(), "not_applicable")

    def test_unknown_price_is_never_a_number(self):
        r = poisk.budget_result(self.candidate, self.candidate["opportunities"][0], self.brief, TODAY)
        self.assertEqual(r["status"], "limited_package_to_price")
        self.assertIsNone(r["price_range"])
        self.assertEqual(r["confidence"], "hypothesis")

    def hypothesis(self):
        return {"assessment": "plausible", "brief_id": self.brief["id"],
                "budget_amount": 100000, "currency": "USD", "months": 12, "budget_scope": "all_in",
                "reason": "Синтетическая гипотеза для проверки версионирования",
                "assumptions": ["Условия и ставка неизвестны"]}

    def test_budget_hypothesis_is_bound_to_actual_amount(self):
        self.candidate["opportunities"][0]["budget_hypothesis"] = self.hypothesis()
        self.brief["budget"]["amount"] = 1
        r = poisk.budget_result(self.candidate, self.candidate["opportunities"][0], self.brief, TODAY)
        self.assertEqual(r["status"], "reassess_budget_hypothesis")
        self.assertIsNone(r["hypothesis"])

    def test_budget_hypothesis_is_bound_to_brief_version(self):
        self.candidate["opportunities"][0]["budget_hypothesis"] = self.hypothesis()
        self.brief["id"] = "different-brand-v2"
        r = poisk.budget_result(self.candidate, self.candidate["opportunities"][0], self.brief, TODAY)
        self.assertEqual(r["status"], "reassess_budget_hypothesis")

    def test_bound_plausibility_remains_a_hypothesis(self):
        self.candidate["opportunities"][0]["budget_hypothesis"] = self.hypothesis()
        r = poisk.budget_result(self.candidate, self.candidate["opportunities"][0], self.brief, TODAY)
        self.assertEqual(r["status"], "plausible_unpriced")
        self.assertIsNone(r["price_range"])

    def test_supported_range_keeps_estimate_status(self):
        r = self.budget()
        self.assertEqual(r["status"], "within_observed_range")
        self.assertEqual(r["confidence"], "estimate")

    def test_fee_requires_other_costs_for_all_in_budget(self):
        self.assertEqual(self.budget(cost_basis="fee_only")["status"], "need_full_cost")

    def test_known_extra_costs_reduce_fee_ceiling(self):
        self.brief["budget"]["non_fee_costs"] = 10000
        r = self.budget(cost_basis="fee_only", low=85000, high=95000)
        self.assertEqual(r["status"], "overlapping_range")
        self.assertEqual(r["comparison_ceiling"], 90000)

    def test_over_budget_range_is_visible(self):
        self.assertEqual(self.budget(low=110000, high=140000)["status"], "over_observed_range")

    def test_currency_is_not_silently_converted(self):
        self.assertEqual(self.budget(currency="CLP")["status"], "incomparable")

    def test_single_activation_is_not_annualized(self):
        self.assertEqual(self.budget(months=1)["status"], "incomparable")

    def test_different_rights_are_not_comparable(self):
        self.assertEqual(self.budget(scope_match=False)["status"], "incomparable")

    def test_old_price_does_not_pass_budget_gate(self):
        self.assertEqual(self.budget(valid_until="2026-09-29")["status"], "stale_price")

    def test_course_price_is_rejected(self):
        self.corpus["candidates"][0]["opportunities"][0]["cost"] = self.cost(source_price_kind="course")
        with self.assertRaisesRegex(ValueError, "курса"):
            poisk.review(self.brief, self.corpus, TODAY)

    def test_global_exclusive_unknown_is_not_priority(self):
        self.corpus["candidates"][0]["opportunities"][0]["scope"] = "global_exclusive"
        r = poisk.review(self.brief, self.corpus, TODAY)
        row = next(x for x in r["rows"] if x["candidate_id"] == "patagonman")
        self.assertEqual(row["segment"], "needs_data")
        self.assertEqual(row["budget"]["status"], "global_exclusive_requires_quote")

    def test_chilean_origin_is_not_audience_geo(self):
        r = poisk.review(self.brief, self.corpus, TODAY)
        self.assertTrue(all(x["audience_geo"] == "needs_audience_geo" for x in r["rows"]))
        self.assertIsNone(r["numeric_suitability_score"])

    def test_search_snippets_cannot_be_evidence(self):
        self.corpus["evidence"][0]["access"] = "search_snippet"
        with self.assertRaisesRegex(ValueError, "Сниппет"):
            poisk.review(self.brief, self.corpus, TODAY)

    def test_confirmed_block_requires_human_review(self):
        self.corpus["candidates"][0]["risk"] = {"status": "confirmed_block", "evidence_ids": ["E-PATA-SP"]}
        with self.assertRaisesRegex(ValueError, "человеком"):
            poisk.review(self.brief, self.corpus, TODAY)

    def test_unknown_source_id_is_rejected(self):
        self.corpus["candidates"][0]["topic_claims"][0]["evidence_ids"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "Неизвестный ID"):
            poisk.review(self.brief, self.corpus, TODAY)

    def test_duplicate_identity_keeps_trace(self):
        clone = copy.deepcopy(self.corpus["candidates"][0])
        clone["id"] = "duplicate"
        self.corpus["candidates"].append(clone)
        r = poisk.review(self.brief, self.corpus, TODAY)
        self.assertEqual(len(r["rows"]), 7)
        self.assertEqual(r["duplicates"], [{"id": "duplicate", "duplicate_of": "patagonman"}])

    def test_conflicting_duplicate_dossier_is_not_silently_merged(self):
        clone = copy.deepcopy(self.corpus["candidates"][0])
        clone["id"] = "duplicate"
        clone["name"] = "Another rights holder"
        self.corpus["candidates"].append(clone)
        with self.assertRaisesRegex(ValueError, "Конфликт"):
            poisk.review(self.brief, self.corpus, TODAY)

    def test_plan_covers_adjacent_lane_with_default_limit(self):
        p = poisk.make_plan(self.brief, self.packs)
        self.assertEqual(len(p["scheduled"]), 18)
        self.assertEqual(len(p["deferred"]), 18)
        self.assertEqual({x["lane"] for x in p["scheduled"]}, {"direct", "audience", "adjacent"})
        self.assertEqual(len({x["category"] for x in p["scheduled"]}), 6)
        self.assertFalse(p["network_executed"])

    def test_brazil_has_portuguese_queries(self):
        self.brief["geo"] = ["BR"]
        p = poisk.make_plan(self.brief, self.packs)
        self.assertTrue(all(x["language"] == "pt" for x in p["scheduled"]))
        self.assertEqual(p["source_seeds"]["BR"], [])

    def test_zero_limit_does_not_schedule_queries(self):
        self.brief["advanced"]["max_search_calls"] = 0
        p = poisk.make_plan(self.brief, self.packs)
        self.assertEqual(p["scheduled"], [])
        self.assertEqual(len(p["deferred"]), 36)

    def test_boolean_is_not_a_budget_number(self):
        self.brief["budget"]["amount"] = True
        with self.assertRaises(ValueError):
            poisk.make_plan(self.brief, self.packs)

    def test_negative_follower_override_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "min_followers"):
            poisk.make_plan(self.brief, self.packs, -1)

    def test_future_metric_is_rejected(self):
        self.corpus["candidates"][0]["metrics"] = [self.metric(100000, observed="2026-10-01")]
        with self.assertRaisesRegex(ValueError, "будущем"):
            poisk.review(self.brief, self.corpus, TODAY)


if __name__ == "__main__":
    unittest.main()
