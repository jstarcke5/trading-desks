"""Book integrity. Found by red team 2026-08-19 — four confirmed defects:

1. ref_id was minted per CALL, not per logical order, so the idempotency key protected nothing
   and a retry became a second position. Worse than absent: the comment claimed protection.
2. notional_today / realized_pnl_today never reset. They accumulate forever, so the daily cap
   ratchets permanently shut and the loss cap eventually halts the system for good.
3. Nothing ever reconciled our beliefs against the broker. A fill that lands after a timeout is
   invisible to EVERY control at once — no cap, no exposure limit, no flatten plan sees it.
4. commit() assumed the full requested amount filled. Partial fills silently corrupted exposure.
"""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import ledger  # noqa: E402


class IdempotencyTest(unittest.TestCase):
    ORDER = {"symbol": "SPY", "side": "buy", "type": "market", "dollar_amount": "15.00"}

    def test_same_logical_order_yields_the_same_key(self):
        a = ledger.ref_id_for(self.ORDER, session_id="s1")
        b = ledger.ref_id_for(self.ORDER, session_id="s1")
        self.assertEqual(a, b, "a retry must reuse the key, or it becomes a second order")

    def test_a_different_amount_is_a_different_order(self):
        other = dict(self.ORDER, dollar_amount="16.00")
        self.assertNotEqual(ledger.ref_id_for(self.ORDER, "s1"), ledger.ref_id_for(other, "s1"))

    def test_a_different_side_is_a_different_order(self):
        other = dict(self.ORDER, side="sell")
        self.assertNotEqual(ledger.ref_id_for(self.ORDER, "s1"), ledger.ref_id_for(other, "s1"))

    def test_a_later_session_may_repeat_the_same_trade(self):
        self.assertNotEqual(ledger.ref_id_for(self.ORDER, "s1"), ledger.ref_id_for(self.ORDER, "s2"))

    def test_the_key_is_a_valid_uuid_shape(self):
        self.assertEqual(len(ledger.ref_id_for(self.ORDER, "s1")), 36)


class DailyResetTest(unittest.TestCase):
    def test_counters_carry_within_the_same_day(self):
        s = {"as_of": "2026-08-19", "notional_today": 40.0, "realized_pnl_today": -3.0}
        out = ledger.roll(s, "2026-08-19")
        self.assertEqual(out["notional_today"], 40.0)
        self.assertEqual(out["realized_pnl_today"], -3.0)

    def test_counters_reset_on_a_new_day(self):
        s = {"as_of": "2026-08-18", "notional_today": 40.0, "realized_pnl_today": -12.0}
        out = ledger.roll(s, "2026-08-19")
        self.assertEqual(out["notional_today"], 0.0)
        self.assertEqual(out["realized_pnl_today"], 0.0)

    def test_positions_survive_a_day_roll(self):
        s = {"as_of": "2026-08-18", "positions": {"SPY": {"quantity": 2.0}}}
        self.assertIn("SPY", ledger.roll(s, "2026-08-19")["positions"])

    def test_missing_as_of_is_treated_as_a_new_day(self):
        out = ledger.roll({"notional_today": 40.0}, "2026-08-19")
        self.assertEqual(out["notional_today"], 0.0, "unknown vintage must not be trusted")

    def test_the_roll_stamps_the_new_date(self):
        self.assertEqual(ledger.roll({}, "2026-08-19")["as_of"], "2026-08-19")


class ReconcileTest(unittest.TestCase):
    """The broker is the truth. Our file is a cache, and a cache that is never checked is a lie
    waiting to be believed."""

    def test_a_position_we_do_not_know_about_is_adopted(self):
        local = {"positions": {}}
        broker = [{"symbol": "SPY", "quantity": "2.0"}]
        out, drift = ledger.reconcile(local, broker)
        self.assertIn("SPY", out["positions"])
        self.assertTrue(any("unknown" in d for d in drift))

    def test_a_position_that_no_longer_exists_is_dropped(self):
        local = {"positions": {"QQQ": {"quantity": 1.0, "opened_at": "2026-08-19T10:00:00"}}}
        out, drift = ledger.reconcile(local, [])
        self.assertNotIn("QQQ", out["positions"])
        self.assertTrue(any("gone" in d for d in drift))

    def test_a_quantity_mismatch_takes_the_brokers_number(self):
        local = {"positions": {"SPY": {"quantity": 5.0, "opened_at": "2026-08-19T10:00:00"}}}
        out, drift = ledger.reconcile(local, [{"symbol": "SPY", "quantity": "3.0"}])
        self.assertEqual(out["positions"]["SPY"]["quantity"], 3.0)
        self.assertTrue(any("quantity" in d for d in drift))

    def test_an_adopted_position_keeps_a_conservative_open_time(self):
        """An unknown position must not look freshly opened — that would let min_hold be
        evaded, and it must not look ancient either. Unknown means unknown."""
        out, _ = ledger.reconcile({"positions": {}}, [{"symbol": "SPY", "quantity": "2.0"}])
        self.assertIsNone(out["positions"]["SPY"].get("opened_at"))

    def test_a_clean_book_reports_no_drift(self):
        local = {"positions": {"SPY": {"quantity": 2.0, "opened_at": "2026-08-19T10:00:00"}}}
        out, drift = ledger.reconcile(local, [{"symbol": "SPY", "quantity": "2.0"}])
        self.assertEqual(drift, [])

    def test_exposure_is_recomputed_from_the_reconciled_book(self):
        out, _ = ledger.reconcile({"positions": {}},
                                  [{"symbol": "SPY", "quantity": "2.0", "market_value": "24.00"}])
        self.assertAlmostEqual(out["open_exposure"], 24.0)


class PartialFillTest(unittest.TestCase):
    def test_only_the_filled_amount_is_recorded(self):
        out = ledger.apply_fill({"positions": {}, "notional_today": 0.0},
                                symbol="SPY", side="buy", filled_qty=1.2, filled_notional=12.0,
                                now="2026-08-19T10:05:00")
        self.assertAlmostEqual(out["notional_today"], 12.0)
        self.assertAlmostEqual(out["positions"]["SPY"]["quantity"], 1.2)

    def test_a_zero_fill_records_nothing(self):
        out = ledger.apply_fill({"positions": {}, "notional_today": 0.0}, "SPY", "buy",
                                0.0, 0.0, "2026-08-19T10:05:00")
        self.assertEqual(out["positions"], {})
        self.assertEqual(out["notional_today"], 0.0)

    def test_a_sell_reduces_and_removes_when_flat(self):
        s = {"positions": {"SPY": {"quantity": 2.0, "opened_at": "x"}}, "notional_today": 0.0}
        out = ledger.apply_fill(s, "SPY", "sell", 2.0, 24.0, "2026-08-19T11:00:00")
        self.assertNotIn("SPY", out["positions"])

    def test_selling_more_than_held_never_goes_negative(self):
        s = {"positions": {"SPY": {"quantity": 1.0, "opened_at": "x"}}, "notional_today": 0.0}
        out = ledger.apply_fill(s, "SPY", "sell", 5.0, 60.0, "2026-08-19T11:00:00")
        self.assertNotIn("SPY", out["positions"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
