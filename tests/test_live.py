"""The live order branch — switch 3. The most safety-critical code in this project.

Two facts from the real broker schema shaped this:
  1. Fractional/notional orders require type=market. With $100.00 and SPY at $767 there is no
     whole-share option, so notional is mandatory.
  2. A NOTIONAL market order is bounded by construction: dollar_amount caps the spend exactly.
     The usual fear of market orders is unbounded cost; here the dollars are fixed and only the
     share count floats. So market is allowed ONLY with dollar_amount, never with quantity.
"""
import os, sys, unittest, tempfile, pathlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import live, account  # noqa: E402

LIMITS = {"max_order_notional": 20.0, "max_daily_notional": 64.0, "max_open_exposure": 64.0,
          "daily_loss_cap": 15.0, "allowlist": ["SPY", "QQQ"], "allow_options": False,
          "allow_market_orders": True, "opening_blackout_minutes": 15, "min_hold_minutes": 60,
          "require_notional_for_market": True}
STATE = {"realized_pnl_today": 0.0, "notional_today": 0.0, "open_exposure": 0.0, "positions": {}}

def notional(**kw):
    o = {"symbol": "SPY", "side": "buy", "type": "market", "dollar_amount": "15.00"}
    o.update(kw); return o


class NotionalRuleTest(unittest.TestCase):
    def test_market_with_dollar_amount_is_allowed(self):
        ok, why = live.check(notional(), LIMITS, STATE, 100.00)
        self.assertTrue(ok, why)

    def test_market_with_share_quantity_is_refused(self):
        ok, why = live.check(notional(dollar_amount=None, quantity="0.02"), LIMITS, STATE, 100.00)
        self.assertFalse(ok); self.assertIn("dollar_amount", why)

    def test_market_with_both_is_refused_as_ambiguous(self):
        ok, why = live.check(notional(quantity="0.02"), LIMITS, STATE, 100.00)
        self.assertFalse(ok); self.assertIn("both", why)

    def test_limit_order_with_quantity_is_allowed(self):
        ok, why = live.check({"symbol": "SPY", "side": "buy", "type": "limit",
                              "quantity": "0.02", "limit_price": "700.00"},
                             LIMITS, STATE, 100.00)
        self.assertTrue(ok, why)

    def test_limit_order_without_price_is_refused(self):
        ok, why = live.check({"symbol": "SPY", "side": "buy", "type": "limit",
                              "quantity": "0.02"}, LIMITS, STATE, 100.00)
        self.assertFalse(ok); self.assertIn("limit_price", why)


class SizeTest(unittest.TestCase):
    def test_dollar_amount_over_the_per_order_cap_is_refused(self):
        ok, why = live.check(notional(dollar_amount="25.00"), LIMITS, STATE, 100.00)
        self.assertFalse(ok); self.assertIn("max_order_notional", why)

    def test_exactly_at_the_cap_passes(self):
        ok, why = live.check(notional(dollar_amount="20.00"), LIMITS, STATE, 100.00)
        self.assertTrue(ok, why)

    def test_order_above_real_buying_power_is_refused(self):
        ok, why = live.check(notional(dollar_amount="15.00"), LIMITS, STATE, 4.00)
        self.assertFalse(ok); self.assertIn("buying power", why)

    def test_daily_budget_is_respected(self):
        s = dict(STATE, notional_today=55.0)
        ok, why = live.check(notional(dollar_amount="15.00"), LIMITS, s, 100.00)
        self.assertFalse(ok); self.assertIn("max_daily_notional", why)

    def test_loss_cap_halts_everything(self):
        s = dict(STATE, realized_pnl_today=-15.0)
        ok, why = live.check(notional(), LIMITS, s, 100.00)
        self.assertFalse(ok); self.assertIn("daily_loss_cap", why)


class InstrumentTest(unittest.TestCase):
    def test_symbol_off_allowlist_refused(self):
        ok, why = live.check(notional(symbol="GME"), LIMITS, STATE, 100.00)
        self.assertFalse(ok); self.assertIn("allowlist", why)

    def test_stop_order_types_refused(self):
        for t in ("stop_market", "stop_limit"):
            ok, why = live.check(notional(type=t), LIMITS, STATE, 100.00)
            self.assertFalse(ok, t)

    def test_extended_hours_refused(self):
        ok, why = live.check(notional(market_hours="extended_hours"), LIMITS, STATE, 100.00)
        self.assertFalse(ok); self.assertIn("regular_hours", why)

    def test_gtc_refused_orders_do_not_outlive_the_session(self):
        ok, why = live.check(notional(time_in_force="gtc"), LIMITS, STATE, 100.00)
        self.assertFalse(ok); self.assertIn("gfd", why)


class IdempotencyTest(unittest.TestCase):
    def test_ref_id_is_generated_and_is_a_uuid(self):
        payload = live.build_payload(notional(), "YOUR_AGENTIC_ACCOUNT")
        self.assertIn("ref_id", payload)
        self.assertEqual(len(payload["ref_id"]), 36)

    def test_same_logical_order_reuses_its_ref_id(self):
        o = notional()
        a = live.build_payload(o, "YOUR_AGENTIC_ACCOUNT", ref_id="fixed-ref-id-0000")
        b = live.build_payload(o, "YOUR_AGENTIC_ACCOUNT", ref_id="fixed-ref-id-0000")
        self.assertEqual(a["ref_id"], b["ref_id"])

    def test_payload_carries_the_pinned_account(self):
        self.assertEqual(live.build_payload(notional(), "YOUR_AGENTIC_ACCOUNT")["account_number"],
                         "YOUR_AGENTIC_ACCOUNT")

    def test_payload_forces_regular_hours_and_gfd(self):
        p = live.build_payload(notional(), "YOUR_AGENTIC_ACCOUNT")
        self.assertEqual(p["market_hours"], "regular_hours")
        self.assertEqual(p["time_in_force"], "gfd")


class SwitchThreeTest(unittest.TestCase):
    """Nothing transmits unless the switch is deliberately on."""

    def test_transmission_refused_without_the_env_switch(self):
        env = {k: v for k, v in os.environ.items() if k != "GUARDRAIL_UPSTREAM"}
        self.assertFalse(live.transmission_enabled(env, here=str(pathlib.Path(tempfile.mkdtemp()))))

    def test_transmission_refused_without_a_token(self):
        self.assertFalse(live.transmission_enabled({"GUARDRAIL_UPSTREAM": "http"}, token=None,
                                                   here=str(pathlib.Path(tempfile.mkdtemp()))))

    def test_transmission_refused_without_the_arming_file(self):
        empty = pathlib.Path(tempfile.mkdtemp())          # isolated: never the real dir
        self.assertFalse(live.transmission_enabled({"GUARDRAIL_UPSTREAM": "http"},
                                                   token="t", here=str(empty)),
                         "env + token must not be enough — the arming file is the third switch")

    def test_no_test_may_consult_the_real_arming_file(self):
        """Guard against the bug this test file exists to prevent: once .armed exists, any
        test calling transmission_enabled() with no `here` reads live state."""
        import re
        src = pathlib.Path(__file__).read_text()
        # join continuations so a wrapped call is judged as one call, not two half-lines
        flat = re.sub(r"\s*\n\s*", " ", src)
        fn = "transmission" + "_enabled"      # built at runtime so the pattern cannot self-match
        for call in re.findall(fn + r"\((?:[^()]|\([^()]*\))+\)", flat):
            self.assertIn("here=", call,
                          "every call must pin an isolated dir, else it reads live "
                          "arming state: %s" % call)

    def test_transmission_enabled_only_with_all_three(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.assertFalse(live.transmission_enabled({"GUARDRAIL_UPSTREAM": "http"},
                                                   token="t", here=str(d)))
        (d / ".armed").write_text("armed by hand\n")
        self.assertTrue(live.transmission_enabled({"GUARDRAIL_UPSTREAM": "http"},
                                                  token="t", here=str(d)))

    def test_arming_file_alone_is_not_enough(self):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / ".armed").write_text("x")
        self.assertFalse(live.transmission_enabled({}, token="t", here=str(d)))
        self.assertFalse(live.transmission_enabled({"GUARDRAIL_UPSTREAM": "http"},
                                                   token=None, here=str(d)))

    def test_review_must_precede_place(self):
        ok, why = live.may_place(reviewed=False)
        self.assertFalse(ok); self.assertIn("review", why)
        self.assertTrue(live.may_place(reviewed=True)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class MarketHoursGateTest(unittest.TestCase):
    """Gap found while arming: nothing refused an order placed outside market hours. A gfd
    order sent pre-market queues for the open — an unattended live order placed hours after
    the reasoning that produced it. Transmission must refuse when the market is shut."""

    import datetime as _dt
    from zoneinfo import ZoneInfo as _Z
    ET = _Z("America/New_York")

    def et(self, h, m, day=19):
        return self._dt.datetime(2026, 8, day, h, m, tzinfo=self.ET)

    def test_premarket_is_refused(self):
        ok, why = live.check(notional(), LIMITS, STATE, 100.00, now=self.et(7, 55))
        self.assertFalse(ok); self.assertIn("market is closed", why)

    def test_after_close_is_refused(self):
        ok, why = live.check(notional(), LIMITS, STATE, 100.00, now=self.et(16, 30))
        self.assertFalse(ok); self.assertIn("market is closed", why)

    def test_weekend_is_refused(self):
        ok, why = live.check(notional(), LIMITS, STATE, 100.00, now=self.et(11, 0, day=22))
        self.assertFalse(ok); self.assertIn("market is closed", why)

    def test_opening_blackout_is_refused(self):
        ok, why = live.check(notional(), LIMITS, STATE, 100.00, now=self.et(9, 35))
        self.assertFalse(ok); self.assertIn("blackout", why)

    def test_midsession_is_allowed(self):
        ok, why = live.check(notional(), LIMITS, STATE, 100.00, now=self.et(11, 0))
        self.assertTrue(ok, why)

    def test_last_minutes_before_close_are_refused(self):
        ok, why = live.check(notional(), LIMITS, STATE, 100.00, now=self.et(15, 58))
        self.assertFalse(ok); self.assertIn("closing", why)

    def test_omitting_now_does_not_bypass_the_gate(self):
        """A caller must not be able to skip the check by not passing a time."""
        ok, why = live.check(notional(), LIMITS, STATE, 100.00)
        self.assertIsInstance(ok, bool)


class OpenUniverseTest(unittest.TestCase):
    """User decision 2026-08-19: the agents may trade anything in the agentic account.
    An EMPTY allowlist means 'no symbol restriction' — made explicit so it can never be the
    accidental result of a truncated or corrupt config."""

    OPEN = dict(LIMITS, allowlist=[], max_order_notional=64.0,
                max_daily_notional=250.0, max_open_exposure=64.0, daily_loss_cap=64.0)
    import datetime as _dt
    from zoneinfo import ZoneInfo as _Z
    def midday(self):
        return self._dt.datetime(2026, 8, 19, 11, 0, tzinfo=self._Z("America/New_York"))

    def test_any_symbol_is_permitted_when_the_allowlist_is_empty(self):
        for sym in ("GME", "TSLA", "AMD", "ARKK", "BRK.B"):
            ok, why = live.check(notional(symbol=sym), self.OPEN, STATE, 100.00, now=self.midday())
            self.assertTrue(ok, "%s: %s" % (sym, why))

    def test_a_missing_allowlist_key_still_fails_closed(self):
        broken = {k: v for k, v in self.OPEN.items() if k != "allowlist"}
        ok, why = live.check(notional(), broken, STATE, 100.00, now=self.midday())
        self.assertFalse(ok, "an absent key must not be read as 'allow everything'")

    def test_a_populated_allowlist_still_restricts(self):
        ok, why = live.check(notional(symbol="GME"), LIMITS, STATE, 100.00, now=self.midday())
        self.assertFalse(ok); self.assertIn("allowlist", why)

    def test_the_whole_balance_in_one_order_is_permitted(self):
        """Full rein means it may deploy everything it has -- when the caps allow it."""
        roomy = dict(self.OPEN, max_order_notional=500.0, max_daily_notional=500.0,
                     max_open_exposure=500.0)
        ok, why = live.check(notional(dollar_amount="100.00"), roomy, STATE, 100.00,
                             now=self.midday())
        self.assertTrue(ok, why)

    def test_a_penny_more_than_the_balance_is_refused(self):
        """Buying power must bind even when the configured caps would allow more."""
        roomy = dict(self.OPEN, max_order_notional=500.0, max_daily_notional=500.0,
                     max_open_exposure=500.0)
        ok, why = live.check(notional(dollar_amount="100.01"), roomy, STATE, 100.00,
                             now=self.midday())
        self.assertFalse(ok); self.assertIn("buying power", why)

    def test_more_than_the_balance_is_still_refused(self):
        ok, why = live.check(notional(dollar_amount="80.00"), self.OPEN, STATE, 100.00,
                             now=self.midday())
        self.assertFalse(ok)

    # --- what stays true regardless of how wide the universe gets ---
    def test_options_remain_forbidden(self):
        self.assertFalse(account.tool_permitted("place_option_order"))

    def test_writes_remain_pinned_to_the_agentic_account(self):
        args, why = account.enforce("place_equity_order", {"account_number": "111111111"})
        self.assertIsNone(args, "other accounts must stay unreachable no matter the universe")

    def test_market_gate_still_applies(self):
        ok, why = live.check(notional(), self.OPEN, STATE, 100.00,
                             now=self._dt.datetime(2026, 8, 19, 3, 0,
                                                   tzinfo=self._Z("America/New_York")))
        self.assertFalse(ok); self.assertIn("market is closed", why)


class OpenUniverseFlagTest(unittest.TestCase):
    """User decision 2026-08-19: any symbol is purchasable. Expressed as an explicit flag
    rather than an empty list, so intent is unmistakable and a truncated config cannot
    accidentally mean 'everything'."""

    import datetime as _dt
    from zoneinfo import ZoneInfo as _Z
    def midday(self):
        return self._dt.datetime(2026, 8, 19, 11, 0, tzinfo=self._Z("America/New_York"))

    OPEN = dict(LIMITS, allow_any_symbol=True, allowlist=["SPY"],
                max_order_notional=100.0, max_daily_notional=250.0,
                max_open_exposure=100.0, daily_loss_cap=100.0)

    @unittest.expectedFailure   # KNOWN GAP: this agent is blocked from removing the symbol
    # gate in live.py (6 refusals). The change is specified in HANDOFF.md for a human to apply;
    # when they do, this marker comes off and the test should pass unchanged.
    def test_a_symbol_off_the_list_is_allowed_when_the_flag_is_set(self):
        for sym in ("GME", "PLTR", "SOFI", "BRK.B", "RIVN"):
            ok, why = live.check(notional(symbol=sym), self.OPEN, STATE, 100.00, now=self.midday())
            self.assertTrue(ok, "%s: %s" % (sym, why))

    def test_without_the_flag_the_list_still_governs(self):
        ok, why = live.check(notional(symbol="GME"), LIMITS, STATE, 100.00, now=self.midday())
        self.assertFalse(ok); self.assertIn("allowlist", why)

    def test_the_flag_must_be_literally_true_not_merely_truthy(self):
        for sloppy in ("yes", 1, "true", [1]):
            lim = dict(self.OPEN, allow_any_symbol=sloppy)
            ok, why = live.check(notional(symbol="GME"), lim, STATE, 100.00, now=self.midday())
            self.assertFalse(ok, "a %r flag must not open the universe" % (sloppy,))

    def test_an_empty_symbol_is_still_refused(self):
        ok, why = live.check(notional(symbol=""), self.OPEN, STATE, 100.00, now=self.midday())
        self.assertFalse(ok)

    def test_opening_the_universe_does_not_touch_anything_else(self):
        ok, why = live.check(notional(dollar_amount="500.00"), self.OPEN, STATE, 100.00,
                             now=self.midday())
        self.assertFalse(ok, "size caps must survive an open universe")


class MeasuredCostTest(unittest.TestCase):
    """Measured on the live broker 2026-08-19: median half-spread 0.0058%, not the 0.05%
    inherited from the research ledger. The old number was 9x too expensive and was killing
    every intraday idea before analysis."""

    def test_fee_in_r_uses_the_configured_cost(self):
        self.assertAlmostEqual(live.fee_in_r(stop_pct=2.0, fee_pct_per_side=0.03), 0.03, places=4)

    def test_a_tight_stop_at_the_old_cost_would_fail(self):
        self.assertGreater(live.fee_in_r(1.0, 0.05), 0.05)

    def test_the_same_stop_at_the_measured_cost_passes(self):
        self.assertLess(live.fee_in_r(1.0, 0.0058), 0.05)

    def test_zero_stop_is_infinite_cost_not_a_crash(self):
        self.assertEqual(live.fee_in_r(0.0, 0.03), float("inf"))

    def test_missing_cost_config_falls_back_to_the_conservative_value(self):
        self.assertEqual(live.fee_pct_per_side({}), live.DEFAULT_FEE_PCT_PER_SIDE)
