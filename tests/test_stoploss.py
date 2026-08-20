"""The hole an auditor found: a losing position could not be exited.

Three rules combined into a trap nobody wrote down:
  - min_hold_minutes refuses any SELL inside the window, regardless of the loss
  - stop orders are forbidden ("a stop is a second, unreviewed order")
  - the loss cap reads realized P&L only, so an open drawdown trips nothing

A position could therefore run to any loss for a full hour with no automatic exit and no
control reacting. Two fixes: an exit is never blocked by min_hold, and the loss cap must see
unrealized losses.
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import ledger  # noqa: E402


class UnrealizedTest(unittest.TestCase):
    STATE = {"positions": {"SPY": {"quantity": 2.0, "cost_basis": 20.0},
                           "QQQ": {"quantity": 1.0, "cost_basis": 30.0}}}

    def test_unrealized_loss_is_negative(self):
        marks = {"SPY": 8.0, "QQQ": 30.0}          # SPY worth 16 vs 20 cost
        self.assertAlmostEqual(ledger.unrealized(self.STATE, marks), -4.0)

    def test_unrealized_gain_is_positive(self):
        self.assertAlmostEqual(ledger.unrealized(self.STATE, {"SPY": 12.0, "QQQ": 30.0}), 4.0)

    def test_a_missing_mark_is_skipped_not_guessed(self):
        self.assertAlmostEqual(ledger.unrealized(self.STATE, {"SPY": 8.0}), -4.0)

    def test_no_marks_at_all_is_zero_not_a_crash(self):
        self.assertEqual(ledger.unrealized(self.STATE, {}), 0.0)

    def test_missing_cost_basis_is_skipped(self):
        s = {"positions": {"X": {"quantity": 1.0}}}
        self.assertEqual(ledger.unrealized(s, {"X": 5.0}), 0.0)


class TotalExposureTest(unittest.TestCase):
    """The loss cap must see the whole picture, not just closed trades."""

    def test_total_loss_combines_realized_and_unrealized(self):
        s = {"realized_pnl_today": -5.0,
             "positions": {"SPY": {"quantity": 1.0, "cost_basis": 20.0}}}
        self.assertAlmostEqual(ledger.total_pnl(s, {"SPY": 12.0}), -13.0)

    def test_an_open_drawdown_alone_can_breach_the_cap(self):
        s = {"realized_pnl_today": 0.0,
             "positions": {"SPY": {"quantity": 1.0, "cost_basis": 50.0}}}
        total = ledger.total_pnl(s, {"SPY": 30.0})
        self.assertTrue(ledger.halted(total, daily_loss_cap=15.0),
                        "an unrealized -20 must halt against a 15 cap")

    def test_a_healthy_book_is_not_halted(self):
        self.assertFalse(ledger.halted(-2.0, daily_loss_cap=15.0))

    def test_the_cap_is_compared_on_magnitude_not_sign(self):
        self.assertTrue(ledger.halted(-15.0, daily_loss_cap=15.0))
        self.assertFalse(ledger.halted(15.0, daily_loss_cap=15.0), "a GAIN must never halt")


class ExitAlwaysAllowedTest(unittest.TestCase):
    """An exit is never blocked. A hold rule that traps a loser is not a risk control."""

    def test_closing_a_position_is_exempt_from_min_hold(self):
        ok, why = ledger.may_exit(side="sell", held_minutes=5, min_hold_minutes=60,
                                  unrealized_pct=-8.0)
        self.assertTrue(ok, why)

    def test_a_profitable_early_sell_still_respects_min_hold(self):
        ok, why = ledger.may_exit("sell", held_minutes=5, min_hold_minutes=60,
                                  unrealized_pct=+3.0)
        self.assertFalse(ok)
        self.assertIn("min_hold", why)

    def test_a_flat_position_still_respects_min_hold(self):
        self.assertFalse(ledger.may_exit("sell", 5, 60, 0.0)[0])

    def test_after_min_hold_anything_may_be_sold(self):
        self.assertTrue(ledger.may_exit("sell", 90, 60, +3.0)[0])

    def test_a_buy_is_never_governed_by_this(self):
        ok, why = ledger.may_exit("buy", 5, 60, -8.0)
        self.assertTrue(ok, "min_hold governs exits, not entries")

    def test_an_unknown_hold_time_permits_the_exit(self):
        """Reconciliation records opened_at=None for adopted positions. Unknown age must not
        trap a position — refusing to exit is the dangerous direction."""
        self.assertTrue(ledger.may_exit("sell", None, 60, -2.0)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
