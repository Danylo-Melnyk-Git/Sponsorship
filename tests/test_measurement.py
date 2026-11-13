"""Financial identities, statistical references, missingness and file boundaries."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from packages.measurement.engine import analyze, COSTS, wilson
from packages.measurement.report import html, markdown
from sponsor import main

ROOT = Path(__file__).resolve().parents[1]


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.input = json.loads((ROOT / "packages/measurement/examples/synthetic.json").read_text(encoding="utf-8"))

    def set_range(self, target, lo, hi):
        target.update(low=lo, high=hi, status="assumption")

    def test_financial_identity_and_break_even(self):
        e = analyze(self.input)["economics"]
        # 100k rights + 80k activation cost; independent hand calculations.
        self.assertEqual(e["total_cost"], [180000, 180000])
        self.assertEqual(e["break_even_outcomes"], [1500, 2250])
        self.assertEqual(e["target_outcomes"], [1800, 2700])
        self.assertEqual(e["incremental_contribution"], [64000, 288000])
        self.assertEqual(e["net"], [-116000, 108000])
        self.assertAlmostEqual(e["roi"][0], -116/180)
        self.assertAlmostEqual(e["roi"][1], .6)
        self.assertAlmostEqual(e["fee_cap"][0], -26666.66666666667)
        self.assertEqual(e["fee_cap"][1], 160000)
        self.assertEqual(e["versus_alternative"], [-156000, 88000])
        self.assertFalse(e["causal_roi_verified"])

    def test_fee_cap_reconstructs_target_roi(self):
        self.set_range(self.input["economics"]["incremental_outcomes"], 2100, 2100)
        self.set_range(self.input["economics"]["margin_per_outcome"], 100, 100)
        e = analyze(self.input)["economics"]
        cap = e["fee_cap"][0]
        self.assertEqual(cap, 95000)
        self.assertAlmostEqual((210000 - (cap + 80000))/(cap + 80000), .2)

    def test_unknown_cost_never_becomes_zero_or_full_total(self):
        self.input["economics"]["costs"]["measurement"].update(status="unknown", low=None, high=None)
        e = analyze(self.input)["economics"]
        self.assertEqual(e["known_cost_subtotal"], [170000, 170000])
        for key in ("total_cost", "break_even_outcomes", "net", "roi", "fee_cap"):
            self.assertIsNone(e[key])

    def test_unconfirmed_cost_scope_blocks_financial_claims(self):
        self.input["economics"]["cost_scope_complete"] = False
        self.assertIsNone(analyze(self.input)["economics"]["net"])

    def test_missing_outcome_allows_threshold_not_forecast(self):
        self.input["economics"]["incremental_outcomes"].update(status="unknown", low=None, high=None)
        e = analyze(self.input)["economics"]
        self.assertEqual(e["break_even_outcomes"], [1500, 2250])
        self.assertIsNone(e["roi"])

    def test_unknown_margin_keeps_costs_and_blocks_threshold(self):
        self.input["economics"]["margin_per_outcome"].update(status="unknown", low=None, high=None)
        e = analyze(self.input)["economics"]
        self.assertEqual(e["total_cost"], [180000, 180000])
        self.assertIsNone(e["break_even_outcomes"])

    def test_zero_margin_has_no_finite_worst_case_threshold(self):
        self.set_range(self.input["economics"]["margin_per_outcome"], 0, 120)
        e = analyze(self.input)["economics"]
        self.assertIsNone(e["break_even_outcomes"])
        self.assertEqual(e["net"][0], -180000)

    def test_signed_uplift_and_varying_cost_ratio(self):
        self.set_range(self.input["economics"]["incremental_outcomes"], -100, -50)
        self.set_range(self.input["economics"]["costs"]["rights_fee"], 20000, 120000)
        e = analyze(self.input)["economics"]
        self.assertEqual(e["incremental_contribution"], [-12000, -4000])
        # Worst ROI uses smallest denominator for negative contribution.
        self.assertAlmostEqual(e["roi"][0], -1.12)
        self.assertAlmostEqual(e["roi"][1], -1.02)
        self.assertEqual(e["conclusion"], "negative_in_all_bounds")

    def test_zero_cost_roi_is_undefined(self):
        for row in self.input["economics"]["costs"].values():
            self.set_range(row, 0, 0)
        e = analyze(self.input)["economics"]
        self.assertIsNone(e["roi"])
        self.assertEqual(e["break_even_outcomes"], [0, 0])

    def test_sensitivity_has_dollar_units(self):
        s = analyze(self.input)["economics"]["sensitivity"]
        self.assertEqual(s[0]["net_swing"], 160000)
        self.assertEqual(s[1]["net_swing"], 64000)

    def test_wilson_matches_published_nist_example(self):
        # NIST prc241: 26/200 one-sided 95% lower bound 0.09577;
        # equal lower tail to a two-sided 90% interval.
        self.assertAlmostEqual(wilson(26, 200, .1)[0], .09577, places=5)
        self.assertEqual(wilson(0, 10, .05)[0], 0)
        self.assertEqual(wilson(10, 10, .05)[1], 1)

    def test_newcombe_symmetry_and_pp(self):
        s = analyze(self.input)["survey"]
        self.assertAlmostEqual(s["difference_pp"], 6)
        self.assertAlmostEqual(s["relative_difference"], .2)
        self.assertGreater(s["interval_pp"][0], 0)
        self.input["survey"]["treatment"], self.input["survey"]["control"] = self.input["survey"]["control"], self.input["survey"]["treatment"]
        reverse = analyze(self.input)["survey"]
        self.assertAlmostEqual(reverse["interval_pp"][0], -s["interval_pp"][1])
        self.assertAlmostEqual(reverse["interval_pp"][1], -s["interval_pp"][0])

    def test_small_survey_does_not_create_false_zero_precision(self):
        self.input["survey"]["treatment"] = {"yes": 0, "n": 10}
        self.input["survey"]["control"] = {"yes": 0, "n": 10}
        s = analyze(self.input)["survey"]
        self.assertIsNone(s["relative_difference"])
        self.assertLess(s["interval_pp"][0], 0)
        self.assertGreater(s["interval_pp"][1], 0)
        # Inverting the score statistic for zero successes gives z²/(n+z²).
        self.assertAlmostEqual(s["interval_pp"][1], 27.75327998628892, places=8)

    def test_clustered_weighted_paired_survey_does_not_get_naive_ci(self):
        self.input["survey"]["design"] = "clustered_or_weighted_or_paired"
        self.assertIsNone(analyze(self.input)["survey"]["interval_pp"])

    def test_smaller_effect_needs_more_sample(self):
        baseline = analyze(self.input)["sample_plan"]
        self.assertTrue(1370 <= baseline["completed_per_arm"] <= 1380)
        self.input["sample_plan"]["effect_pp"] = 2.5
        larger = analyze(self.input)["sample_plan"]
        self.assertGreater(larger["completed_per_arm"], baseline["completed_per_arm"]*3)

    def test_union_and_joint_bounds_do_not_assume_independence(self):
        a = analyze(self.input)["audience"]
        self.assertEqual(a["union"], [400000, 700000])
        self.assertEqual(a["new_beyond_a"], [0, 300000])
        self.assertAlmostEqual(a["joint_target_share"][0], .3)
        self.assertAlmostEqual(a["joint_target_share"][1], .6)

    def test_known_overlap_collapses_bounds(self):
        self.input["audience"]["overlap"] = 100000
        a = analyze(self.input)["audience"]
        self.assertEqual(a["union"], [600000, 600000])
        self.assertEqual(a["new_beyond_a"], [200000, 200000])

    def test_impossible_overlap_rejected(self):
        self.input["audience"]["overlap"] = 350000
        with self.assertRaises(ValueError):
            analyze(self.input)

    def test_population_upper_bound(self):
        self.input["audience"].update(reach_a=800000, reach_b=700000)
        a = analyze(self.input)["audience"]
        self.assertEqual(a["overlap"], [500000, 700000])
        self.assertEqual(a["union"], [800000, 1000000])

    def test_raters_missing_and_bias(self):
        a = analyze(self.input)["ratings"]
        self.assertEqual(a["paired"], 4)
        self.assertEqual(a["exact_agreement"], .25)
        self.assertEqual(a["mean_absolute_gap"], 25)
        self.assertEqual(a["mean_signed_gap"], 12.5)
        self.assertEqual(len(a["missing"]), 1)
        self.input["ratings"]["rows"] = [{"id": "missing", "a": None, "b": 0}]
        self.assertIsNone(analyze(self.input)["ratings"]["mean_absolute_gap"])

    def test_bad_values_and_hidden_currency_override_rejected(self):
        for value in (True, "100", float("inf"), float("nan"), -1, 10**400):
            with self.subTest(value=value):
                trial = deepcopy(self.input)
                trial["economics"]["costs"]["rights_fee"]["low"] = value
                with self.assertRaises(ValueError):
                    analyze(trial)
        self.input["economics"]["costs"]["rights_fee"]["currency"] = "EUR"
        with self.assertRaises(ValueError):
            analyze(self.input)

    def test_missing_category_source_or_unknown_with_number_rejected(self):
        for mutation in (lambda d: d["economics"]["costs"].pop("other"),
                         lambda d: d["economics"]["margin_per_outcome"].update(source=""),
                         lambda d: d["economics"]["margin_per_outcome"].update(status="unknown")):
            trial = deepcopy(self.input)
            mutation(trial)
            with self.assertRaises(ValueError):
                analyze(trial)

    def test_rater_duplicates_rejected(self):
        self.input["ratings"]["rows"].append(deepcopy(self.input["ratings"]["rows"][0]))
        with self.assertRaises(ValueError):
            analyze(self.input)

    def test_invalid_period_and_counts_rejected(self):
        self.input["scope"]["period_end"] = "2025-01-01"
        with self.assertRaises(ValueError):
            analyze(self.input)
        self.input["scope"]["period_end"] = "2026-12-31"
        self.input["survey"]["treatment"]["yes"] = 1001
        with self.assertRaises(ValueError):
            analyze(self.input)

    def test_pure_function_hash_and_html_escaping(self):
        self.input["title"] = '<script>alert("bad")</script>'
        previous = deepcopy(self.input)
        report = analyze(self.input)
        self.assertEqual(self.input, previous)
        self.assertEqual(report["input_sha256"], analyze(previous)["input_sha256"])
        page = html(report)
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('СИНТЕТИЧЕСКИЙ', page)
        self.assertIn('SHA-256', markdown(report))

    def test_cli_does_not_create_database_or_overwrite(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database, output = root/"missing.sqlite3", root/"result.json"
            args = ["--database", str(database), "measure", "--file", str(ROOT/"packages/measurement/examples/synthetic.json"), "--format", "json", "--out", str(output)]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(args), 0)
                saved = output.read_bytes()
                self.assertEqual(main(args), 1)
            self.assertFalse(database.exists())
            self.assertEqual(saved, output.read_bytes())

    def test_template_is_valid_but_not_calculated(self):
        template = json.loads((ROOT/"packages/measurement/examples/template.json").read_text(encoding="utf-8"))
        report = analyze(template)
        self.assertIsNone(report["economics"]["total_cost"])
        self.assertIn("Не рассчитано", html(report))


if __name__ == "__main__":
    unittest.main()
