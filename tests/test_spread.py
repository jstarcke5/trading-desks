"""Per-symbol cost measurement.

A single fee constant is a guess applied to everything. Measured live 2026-08-19: SPY's
half-spread was 0.0019% while AMD's was 0.0355% — nineteen times wider, in the same minute.
A constant is wrong for both. The fee gate should read the cost of THE symbol being traded,
at the moment of the decision.
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import spread  # noqa: E402


class ParseTest(unittest.TestCase):
    """The payload nests quotes under 'quote' — a flat parser silently found nothing, which
    looked exactly like 'no data' rather than 'wrong shape'."""

    PAYLOAD = {"data": {"results": [
        {"quote": {"symbol": "SPY", "bid_price": "769.63", "ask_price": "769.66"}},
        {"quote": {"symbol": "AMD", "bid_price": "464.39", "ask_price": "464.72"}},
    ]}}

    def test_extracts_both_symbols(self):
        out = spread.parse(self.PAYLOAD)
        self.assertEqual(set(out), {"SPY", "AMD"})

    def test_half_spread_is_correct(self):
        self.assertAlmostEqual(spread.parse(self.PAYLOAD)["SPY"], 0.00195, places=4)

    def test_wide_symbol_is_reported_as_wide(self):
        out = spread.parse(self.PAYLOAD)
        self.assertGreater(out["AMD"], out["SPY"] * 10)

    def test_crossed_or_zero_quotes_are_dropped_not_zeroed(self):
        bad = {"data": {"results": [
            {"quote": {"symbol": "X", "bid_price": "0", "ask_price": "10"}},
            {"quote": {"symbol": "Y", "bid_price": "10", "ask_price": "9"}},
        ]}}
        self.assertEqual(spread.parse(bad), {})

    def test_missing_fields_are_skipped_quietly(self):
        self.assertEqual(spread.parse({"data": {"results": [{"quote": {"symbol": "Z"}}]}}), {})

    def test_empty_payload_is_empty_not_a_crash(self):
        self.assertEqual(spread.parse({}), {})


class GateTest(unittest.TestCase):
    def test_a_tight_symbol_clears_the_gate_at_a_2pct_stop(self):
        ok, detail = spread.cost_gate(half_spread_pct=0.0019, stop_pct=2.0)
        self.assertTrue(ok, detail)

    def test_a_wide_symbol_is_penalised(self):
        tight = spread.effective_fee(0.0019)
        wide = spread.effective_fee(0.0355)
        self.assertGreater(wide, tight)

    def test_a_tight_stop_on_a_wide_symbol_fails(self):
        ok, detail = spread.cost_gate(half_spread_pct=0.0355, stop_pct=0.3)
        self.assertFalse(ok)
        self.assertIn("fee-in-R", detail)

    def test_the_safety_multiple_is_applied_not_the_raw_quote(self):
        """Quoted spread is not the whole cost — fractional market orders can fill outside it."""
        self.assertAlmostEqual(spread.effective_fee(0.01), 0.05, places=6)

    def test_an_unmeasurable_symbol_falls_back_to_the_conservative_constant(self):
        self.assertEqual(spread.effective_fee(None), spread.FALLBACK_FEE_PCT)

    def test_an_absurd_spread_is_refused_rather_than_used(self):
        ok, detail = spread.cost_gate(half_spread_pct=12.0, stop_pct=5.0)
        self.assertFalse(ok)
        self.assertIn("implausible", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
