"""Guardrail proxy — enforcement tests. Stdlib only (python3.9, no pandas/numpy)."""
import unittest, sys, os, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import guard  # noqa: E402

LIMITS = {
    "max_order_notional": 25.0,
    "max_daily_notional": 100.0,
    "max_open_exposure": 60.0,
    "daily_loss_cap": 15.0,
    "allowlist": ["SPY", "QQQ"],
    "allow_options": False,
    "allow_market_orders": False,
    "opening_blackout_minutes": 15,
    "min_hold_minutes": 60,
}
OPEN = datetime.time(9, 30)

def at(h, m):
    return datetime.datetime(2026, 8, 18, h, m)

def state(**kw):
    s = {"realized_pnl_today": 0.0, "notional_today": 0.0,
         "open_exposure": 0.0, "positions": {}}
    s.update(kw)
    return s

def order(**kw):
    o = {"symbol": "SPY", "side": "buy", "quantity": 1.0, "limit_price": 10.0,
         "order_type": "limit", "asset_class": "equity"}
    o.update(kw)
    return o


class TheNonNegotiableTest(unittest.TestCase):
    """From HANDOFF.md §5: a cap nobody has watched reject something is a comment, not a cap."""

    def test_ten_times_the_cap_is_refused(self):
        d = guard.evaluate(order(quantity=25.0, limit_price=10.0), LIMITS, state(), at(11, 0), OPEN)
        self.assertFalse(d.ok)
        self.assertIn("max_order_notional", d.reason)

    def test_refusal_never_reports_ok(self):
        for q in (25.0, 100.0, 1e6):
            self.assertFalse(guard.evaluate(order(quantity=q), LIMITS, state(), at(11, 0), OPEN).ok)


class SizeTest(unittest.TestCase):
    def test_under_cap_passes(self):
        self.assertTrue(guard.evaluate(order(quantity=2.0), LIMITS, state(), at(11, 0), OPEN).ok)

    def test_exactly_at_cap_passes(self):
        d = guard.evaluate(order(quantity=2.5, limit_price=10.0), LIMITS, state(), at(11, 0), OPEN)
        self.assertTrue(d.ok, d.reason)

    def test_one_cent_over_cap_refused(self):
        d = guard.evaluate(order(quantity=2.501), LIMITS, state(), at(11, 0), OPEN)
        self.assertFalse(d.ok)

    def test_daily_notional_budget_exhausted(self):
        d = guard.evaluate(order(quantity=2.0), LIMITS, state(notional_today=95.0), at(11, 0), OPEN)
        self.assertFalse(d.ok)
        self.assertIn("max_daily_notional", d.reason)

    def test_open_exposure_cap(self):
        d = guard.evaluate(order(quantity=2.0), LIMITS, state(open_exposure=55.0), at(11, 0), OPEN)
        self.assertFalse(d.ok)
        self.assertIn("max_open_exposure", d.reason)


class HaltTest(unittest.TestCase):
    def test_daily_loss_cap_halts_everything(self):
        d = guard.evaluate(order(quantity=1.0), LIMITS, state(realized_pnl_today=-15.0), at(11, 0), OPEN)
        self.assertFalse(d.ok)
        self.assertIn("daily_loss_cap", d.reason)

    def test_halt_applies_to_sells_too(self):
        d = guard.evaluate(order(side="sell"), LIMITS, state(realized_pnl_today=-20.0), at(11, 0), OPEN)
        self.assertFalse(d.ok)


class InstrumentTest(unittest.TestCase):
    def test_symbol_not_on_allowlist_refused(self):
        d = guard.evaluate(order(symbol="GME"), LIMITS, state(), at(11, 0), OPEN)
        self.assertFalse(d.ok)
        self.assertIn("allowlist", d.reason)

    def test_options_refused(self):
        d = guard.evaluate(order(asset_class="option"), LIMITS, state(), at(11, 0), OPEN)
        self.assertFalse(d.ok)

    def test_market_order_refused_when_disallowed(self):
        d = guard.evaluate(order(order_type="market"), LIMITS, state(), at(11, 0), OPEN)
        self.assertFalse(d.ok)


class TimingTest(unittest.TestCase):
    def test_market_order_in_opening_blackout_refused(self):
        lim = dict(LIMITS, allow_market_orders=True)
        d = guard.evaluate(order(order_type="market"), lim, state(), at(9, 35), OPEN)
        self.assertFalse(d.ok)
        self.assertIn("blackout", d.reason)

    def test_limit_order_in_blackout_allowed(self):
        d = guard.evaluate(order(), LIMITS, state(), at(9, 35), OPEN)
        self.assertTrue(d.ok, d.reason)

    def test_market_order_after_blackout_allowed(self):
        lim = dict(LIMITS, allow_market_orders=True)
        self.assertTrue(guard.evaluate(order(order_type="market"), lim, state(), at(9, 46), OPEN).ok)

    def test_sell_inside_min_hold_refused(self):
        s = state(positions={"SPY": {"opened_at": "2026-08-18T10:30:00", "quantity": 5.0}})
        d = guard.evaluate(order(side="sell"), LIMITS, s, at(11, 0), OPEN)
        self.assertFalse(d.ok)
        self.assertIn("min_hold_minutes", d.reason)

    def test_sell_after_min_hold_allowed(self):
        s = state(positions={"SPY": {"opened_at": "2026-08-18T09:30:00", "quantity": 5.0}})
        self.assertTrue(guard.evaluate(order(side="sell"), LIMITS, s, at(11, 0), OPEN).ok)


class FailClosedTest(unittest.TestCase):
    def test_missing_field_refused(self):
        o = order(); del o["limit_price"]
        self.assertFalse(guard.evaluate(o, LIMITS, state(), at(11, 0), OPEN).ok)

    def test_unknown_field_refused(self):
        self.assertFalse(guard.evaluate(order(leverage=3), LIMITS, state(), at(11, 0), OPEN).ok)

    def test_non_numeric_quantity_refused(self):
        self.assertFalse(guard.evaluate(order(quantity="lots"), LIMITS, state(), at(11, 0), OPEN).ok)

    def test_zero_and_negative_quantity_refused(self):
        for q in (0, -1.0):
            self.assertFalse(guard.evaluate(order(quantity=q), LIMITS, state(), at(11, 0), OPEN).ok)

    def test_missing_limit_key_refused(self):
        lim = dict(LIMITS); del lim["max_order_notional"]
        self.assertFalse(guard.evaluate(order(), lim, state(), at(11, 0), OPEN).ok)

    def test_unknown_side_refused(self):
        self.assertFalse(guard.evaluate(order(side="short"), LIMITS, state(), at(11, 0), OPEN).ok)


class ModeTest(unittest.TestCase):
    def test_read_modes_expose_no_order_tool(self):
        for mode in ("read-market", "read-portfolio"):
            self.assertNotIn("place_order", guard.tools_for_mode(mode))

    def test_orders_mode_exposes_place_order(self):
        self.assertIn("place_order", guard.tools_for_mode("orders"))

    def test_unknown_mode_exposes_nothing(self):
        self.assertEqual(guard.tools_for_mode("wide-open"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
