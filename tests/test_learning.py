"""The learning loop. Learns from REJECTIONS, because that is where the sample size is."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "learning"))
import score  # noqa: E402


class BrierTest(unittest.TestCase):
    """Calibration: did stated confidence match what happened?"""

    def test_perfect_confident_correct_scores_zero(self):
        self.assertAlmostEqual(score.brier([(1.0, True), (0.0, False)]), 0.0)

    def test_confidently_wrong_scores_one(self):
        self.assertAlmostEqual(score.brier([(1.0, False)]), 1.0)

    def test_coin_flip_scores_quarter(self):
        self.assertAlmostEqual(score.brier([(0.5, True), (0.5, False)]), 0.25)

    def test_empty_is_none_not_zero(self):
        self.assertIsNone(score.brier([]), "no data must not look like perfect calibration")

    def test_verdict_needs_minimum_sample(self):
        v = score.calibration_verdict([(0.9, True)] * 5)
        self.assertIn("UNDERPOWERED", v)

    def test_overconfidence_is_named(self):
        # says 90% confident, right only 30% of the time, over a real sample
        rows = [(0.9, i < 30) for i in range(100)]
        self.assertIn("OVERCONFIDENT", score.calibration_verdict(rows))


class RejectionScoringTest(unittest.TestCase):
    """The core insight — and the trap. A rejected idea never paid costs, so scoring it
    naively always concludes 'the gates are too strict'. Costs and the stated stop must be
    applied identically, or this becomes a machine for rationalising away discipline."""

    def test_rejection_that_would_have_lost_is_correctly_killed(self):
        r = score.score_rejection(entry=100.0, exit=95.0, stop_pct=5.0, side="buy", fee_bps=5)
        self.assertEqual(r["verdict"], "CORRECTLY KILLED")

    def test_rejection_that_would_have_won_gross_but_not_net_is_still_correctly_killed(self):
        # +6bps gross against 10bps round-trip costs
        r = score.score_rejection(entry=100.0, exit=100.06, stop_pct=5.0, side="buy", fee_bps=5)
        self.assertEqual(r["verdict"], "CORRECTLY KILLED", r)
        self.assertLess(r["net_pct"], 0)

    def test_rejection_that_clears_net_of_costs_is_flagged(self):
        r = score.score_rejection(entry=100.0, exit=108.0, stop_pct=5.0, side="buy", fee_bps=5)
        self.assertEqual(r["verdict"], "WRONGLY KILLED", r)
        self.assertGreater(r["net_pct"], 0)

    def test_stop_would_have_been_hit_first_counts_as_a_loss(self):
        # +8% at the end, but it fell 6% first and the stated stop was 5%
        r = score.score_rejection(entry=100.0, exit=108.0, stop_pct=5.0, side="buy",
                                  fee_bps=5, worst_pct=-6.0)
        self.assertEqual(r["verdict"], "CORRECTLY KILLED",
                         "the stop must be honoured before the outcome is counted")

    def test_costs_are_never_optional(self):
        with self.assertRaises(ValueError):
            score.score_rejection(entry=100.0, exit=108.0, stop_pct=5.0, side="buy", fee_bps=None)

    def test_sell_side_direction_is_handled(self):
        r = score.score_rejection(entry=100.0, exit=92.0, stop_pct=5.0, side="sell", fee_bps=5)
        self.assertEqual(r["verdict"], "WRONGLY KILLED", r)


class GateEfficacyTest(unittest.TestCase):
    """Which gate is doing the work, and is any gate destroying value?"""

    def test_gate_with_no_wrong_kills_is_earning_its_place(self):
        rows = [{"gate": "cost", "verdict": "CORRECTLY KILLED"}] * 40
        out = score.gate_report(rows)
        self.assertEqual(out["cost"]["wrongly_killed"], 0)
        self.assertIn("EARNING", out["cost"]["assessment"])

    def test_gate_killing_mostly_winners_is_flagged_for_review(self):
        rows = [{"gate": "sample", "verdict": "WRONGLY KILLED"} for _ in range(30)]
        rows += [{"gate": "sample", "verdict": "CORRECTLY KILLED"} for _ in range(5)]
        out = score.gate_report(rows)
        self.assertIn("REVIEW", out["sample"]["assessment"])

    def test_small_sample_gate_is_underpowered_not_judged(self):
        out = score.gate_report([{"gate": "beta", "verdict": "WRONGLY KILLED"}] * 3)
        self.assertIn("UNDERPOWERED", out["beta"]["assessment"])


class SafetyTest(unittest.TestCase):
    """Learning updates the map, never the guardrails."""

    def test_writable_paths_exclude_every_guardrail(self):
        for forbidden in ("guardrail/limits.json", "CLAUDE.md", "GOAL.md",
                          "desks/executor.settings.json", "guardrail/server.py"):
            self.assertFalse(score.may_write(forbidden), forbidden)

    def test_only_learning_dir_is_writable(self):
        self.assertTrue(score.may_write("learning/calibration.json"))
        self.assertTrue(score.may_write("learning/priors.json"))
        self.assertFalse(score.may_write("learning/../guardrail/limits.json"),
                         "path traversal must not escape the sandbox")


if __name__ == "__main__":
    unittest.main(verbosity=2)
