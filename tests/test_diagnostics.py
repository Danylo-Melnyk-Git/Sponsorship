"""Behaviour, independent extrema checks and persistence boundaries."""

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import hashlib
from io import StringIO
from itertools import product
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from packages.domain.demo import seed
from packages.domain.models import CRITERIA, ValidationError
from packages.domain.service import ResearchService
from packages.domain.store import Store
from packages.scoring.diagnostics import diagnose, extreme, load_read_only, weight_domain
from packages.scoring.diagnostic_report import html, markdown
from sponsor import main


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.store = Store(self.path)
        self.state = seed(ResearchService(self.store))

    def tearDown(self):
        self.temp.cleanup()

    def row(self, report, suffix):
        return next(r for r in report["rows"] if r["package_id"] == "pkg-demo-" + suffix)

    def add_close_alternative(self):
        package = deepcopy(self.state["packages"][0])
        package["id"] = "pkg-demo-d"
        for key, value in zip(CRITERIA, (90, 76, 72, 86)):
            package["criteria"][key]["value"] = value
        self.state["packages"].append(package)

    def test_zero_radius_reproduces_scores_and_missing_bounds(self):
        report = diagnose(self.state, 0)
        self.assertEqual(self.row(report, "a")["stress_bounds"], [82.0, 82.0])
        self.assertEqual(self.row(report, "c")["stress_bounds"], [49.5, 79.5])
        self.assertIsNone(self.row(report, "c")["base_rank"])
        self.assertEqual(self.row(report, "c")["coverage"], .7)
        request = next(r for r in report["requests"] if r["group"] == "evidence")
        self.assertAlmostEqual(request["tie_score_at_base_weights"], 325 / 3)  # (82 − 49.5) / 0.30: недостижимо в шкале 0–100

    def test_weight_reversal_has_executable_witnesses(self):
        self.add_close_alternative()
        report = diagnose(self.state, 5)
        pair = next(p for p in report["pairs"] if p["a"] == "pkg-demo-a" and p["b"] == "pkg-demo-d")
        self.assertEqual(pair["relation"], "reversal_possible")
        self.assertAlmostEqual(pair["gap_bounds"][0], -.3)
        self.assertAlmostEqual(pair["gap_bounds"][1], 1.5)
        for index, key in enumerate(("min_witness", "max_witness")):
            witness = pair[key]
            self.assertAlmostEqual(sum(witness["weights"].values()), 1)
            actual = sum(witness["weights"][k] * (witness["a_scores"][k] - witness["b_scores"][k]) for k in CRITERIA)
            self.assertAlmostEqual(actual, pair["gap_bounds"][index])
            for k, w in witness["weights"].items():
                self.assertLessEqual(abs(w - self.state["weights"][k]), .05 + 1e-8)

    def test_optimizer_matches_independent_vertex_enumeration(self):
        # Every vertex has at least n-1 active box constraints. No optimizer code is reused.
        values = dict(zip(CRITERIA, (-31, 17, 5, -12)))
        for weights in (self.state["weights"], dict(zip(CRITERIA, (1., 0., 0., 0.)))):
            for radius in (0, 5, 35, 100):
                domain = weight_domain(weights, radius)
                vertices = []
                keys = list(CRITERIA)
                for free in keys:
                    fixed = [k for k in keys if k != free]
                    for sides in product((0, 1), repeat=3):
                        vertex = {k: domain[k][side] for k, side in zip(fixed, sides)}
                        vertex[free] = 1 - sum(vertex.values())
                        if domain[free][0] - 1e-8 <= vertex[free] <= domain[free][1] + 1e-8:
                            vertices.append(sum(vertex[k] * values[k] for k in keys))
                self.assertAlmostEqual(extreme(values, domain)[0], min(vertices))
                self.assertAlmostEqual(extreme(values, domain, True)[0], max(vertices))

    def test_risk_and_budget_blocks_cannot_win_a_pair(self):
        self.state["packages"][0]["fee"].update(low=300000, high=300000)
        report = diagnose(self.state, 100, 100)
        self.assertIn("over_budget", self.row(report, "a")["gates"])
        self.assertIn("risk_review", self.row(report, "b")["gates"])
        self.assertFalse(report["pairs"])
        self.assertIsNone(self.row(report, "b")["conditional_rank_bounds"])

    def test_unknown_fee_does_not_hide_scope_mismatch(self):
        self.state["packages"][2]["territory"] = ["BR"]
        self.state["packages"][2]["months"] = 6
        report = diagnose(self.state, 5)
        row = self.row(report, "c")
        self.assertIn("territory_mismatch", row["gates"])
        self.assertIn("period_mismatch", row["gates"])
        self.assertFalse(row["eligible_for_diagnostic"])

    def test_changed_brief_has_no_score_bounds_or_data_priority(self):
        self.state["brief_version"] += 1
        report = diagnose(self.state, 5)
        self.assertFalse(report["pairs"])
        self.assertTrue(all(r["stress_bounds"] is None and r["base_bounds"] is None for r in report["rows"]))
        self.assertFalse(any(r["group"] == "evidence" for r in report["requests"]))

    def test_source_lead_is_missing_and_not_a_point_estimate(self):
        self.state["sources"][0]["access"] = "search_lead"
        report = diagnose(self.state, 0)
        row = self.row(report, "c")
        self.assertEqual(row["stress_bounds"], [0., 100.])
        self.assertIsNone(row["base_score"])
        self.assertIsNone(row["base_rank"])

    def test_independent_input_bounds_and_extreme_weights(self):
        report = diagnose(self.state, 100, 100)
        self.assertEqual(self.row(report, "a")["stress_bounds"], [0., 100.])
        for bounds in report["weight_domain"].values():
            self.assertEqual(bounds, [0., 1.])

    def test_ties_share_rank_and_stable_dominance_is_preserved(self):
        self.add_close_alternative()
        self.state["packages"][-1]["criteria"] = deepcopy(self.state["packages"][0]["criteria"])
        report = diagnose(self.state, 5)
        pair = next(p for p in report["pairs"] if p["b"] == "pkg-demo-d" and p["a"] == "pkg-demo-a")
        self.assertEqual(pair["relation"], "always_tied")
        self.assertEqual(self.row(report, "d")["base_rank"], 1)
        for entry in self.state["packages"][-1]["criteria"].values():
            entry["value"] = 0
        report = diagnose(self.state, 100)
        pair = next(p for p in report["pairs"] if p["b"] == "pkg-demo-d" and p["a"] == "pkg-demo-a")
        self.assertEqual(pair["relation"], "a_strictly_above")

    def test_invalid_radii_and_weights_fail(self):
        for value in (-1, 101, True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                diagnose(self.state, value)
            with self.subTest(score=value), self.assertRaises(ValidationError):
                diagnose(self.state, 5, value)
        self.state["weights"]["audience"] = .8
        with self.assertRaises(ValidationError):
            diagnose(self.state, 5)

    def test_conditional_rank_bounds_enclose_simultaneous_scenarios(self):
        self.add_close_alternative()
        report = diagnose(self.state, 5)
        pool = [r for r in report["rows"] if r["eligible_for_diagnostic"]]
        scenarios = [self.state["weights"]]
        scenarios += [pair[key]["weights"] for pair in report["pairs"] for key in ("min_witness", "max_witness")]
        for weights in scenarios:
            for missing_value in (0, 50, 100):
                scores = {r["package_id"]: sum(weights[k] * (missing_value if v is None else v)
                                               for k, v in r["score_inputs"].items()) for r in pool}
                for row in pool:
                    rank = 1 + sum(v > scores[row["package_id"]] + 1e-8 for v in scores.values())
                    lo, hi = row["conditional_rank_bounds"]
                    self.assertLessEqual(lo, rank)
                    self.assertLessEqual(rank, hi)

    def test_empty_research_is_a_report_not_a_winner(self):
        self.state["packages"] = []
        report = diagnose(self.state, 5)
        self.assertFalse(report["rows"])
        self.assertFalse(report["pairs"])
        self.assertIn("Нет двух сопоставимых пакетов", html(report))

    def test_report_escapes_untrusted_text(self):
        self.state["title"] = '<script>alert("x")</script>'
        self.state["candidates"][0]["name"] = '<img src=x onerror="alert(1)">'
        report = diagnose(self.state, 5)
        rendered = html(report)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("default-src 'none'", rendered)
        self.assertIn("&lt;script&gt;", markdown(report))

    def test_cli_is_read_only_and_refuses_overwrite(self):
        before_state = deepcopy(self.state)
        before_bytes = hashlib.sha256(self.path.read_bytes()).hexdigest()
        before_history = self.store.history(self.state["id"])
        target = Path(self.temp.name) / "report.html"
        args = ["--database", str(self.path), "diagnose", self.state["id"], "--weight-radius", "5", "--format", "html", "--out", str(target)]
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(args), 0)
            content = target.read_bytes()
            self.assertEqual(main(args), 1)
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(self.store.get(self.state["id"]), before_state)
        self.assertEqual(self.store.history(self.state["id"]), before_history)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before_bytes)
        self.assertEqual(load_read_only(self.path, self.state["id"]), before_state)

    def test_missing_database_is_not_created(self):
        path = Path(self.temp.name) / "absent.sqlite3"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(["--database", str(path), "diagnose", "missing", "--weight-radius", "5"]), 1)
        self.assertFalse(path.exists())

    def test_analysis_does_not_mutate_state(self):
        before = deepcopy(self.state)
        diagnose(self.state, 5, 10)
        self.assertEqual(self.state, before)


if __name__ == "__main__":
    unittest.main()
