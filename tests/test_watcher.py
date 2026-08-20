"""Watcher daemon — threshold detection. Stdlib only. Costs zero tokens by design."""
import datetime, json, os, sys, unittest, tempfile, pathlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "watcher"))
import watch  # noqa: E402

RULES = {
    "market_open": "09:30", "market_close": "16:00",
    "max_bar_age_minutes": 30,
    "rules": [{"symbol": "SPY", "metric": "vol_20d", "op": ">", "threshold": 10.0,
               "baseline": "vol_30d_median"}],
}

def bars(n=40, close=100.0, volume=1_000_000, interpolated=False, flat=False):
    out = []
    for i in range(n):
        c = close if flat else close + (i % 7) - 3
        out.append({"date": "2026-07-%02d" % ((i % 28) + 1), "open": c, "high": c + 1,
                    "low": c - 1, "close": c, "volume": volume,
                    "interpolated": interpolated})
    return out

NOW = datetime.datetime(2026, 8, 18, 11, 0)


class DataSanityTest(unittest.TestCase):
    """The repo's most expensive lesson: fabricated bars look exactly like real ones."""

    def test_interpolated_bars_rejected(self):
        ok, why = watch.data_is_sane(bars(interpolated=True))
        self.assertFalse(ok); self.assertIn("interpolated", why)

    def test_zero_volume_rejected(self):
        ok, why = watch.data_is_sane(bars(volume=0))
        self.assertFalse(ok); self.assertIn("volume", why)

    def test_flat_ohlc_rejected(self):
        b = bars(flat=True)
        for x in b:
            x["open"] = x["high"] = x["low"] = x["close"]
        ok, why = watch.data_is_sane(b)
        self.assertFalse(ok); self.assertIn("flat", why)

    def test_too_few_bars_rejected(self):
        ok, why = watch.data_is_sane(bars(n=3))
        self.assertFalse(ok); self.assertIn("bars", why)

    def test_healthy_bars_pass(self):
        ok, why = watch.data_is_sane(bars())
        self.assertTrue(ok, why)


class MarketHoursTest(unittest.TestCase):
    def test_before_open_is_closed(self):
        self.assertFalse(watch.market_is_open(datetime.datetime(2026, 8, 18, 9, 0), RULES))

    def test_after_close_is_closed(self):
        self.assertFalse(watch.market_is_open(datetime.datetime(2026, 8, 18, 16, 30), RULES))

    def test_weekend_is_closed(self):
        self.assertFalse(watch.market_is_open(datetime.datetime(2026, 8, 22, 11, 0), RULES))

    def test_midday_weekday_is_open(self):
        self.assertTrue(watch.market_is_open(NOW, RULES))


class ThresholdTest(unittest.TestCase):
    def test_no_crossing_emits_nothing(self):
        self.assertEqual(watch.evaluate({"vol_20d": 8.0, "vol_30d_median": 8.1}, RULES["rules"][0]), None)

    def test_crossing_emits_signal(self):
        sig = watch.evaluate({"vol_20d": 11.2, "vol_30d_median": 8.1}, RULES["rules"][0])
        self.assertIsNotNone(sig)
        self.assertEqual(sig["symbol"], "SPY")
        self.assertIn("11.2", sig["observed"])
        self.assertIn("10.0", sig["observed"])

    def test_signal_carries_every_contract_field(self):
        sig = watch.evaluate({"vol_20d": 11.2, "vol_30d_median": 8.1}, RULES["rules"][0])
        for field in ("TYPE", "symbol", "observed", "as_of", "context"):
            self.assertIn(field, sig, field)
        self.assertEqual(sig["TYPE"], "SIGNAL")

    def test_missing_metric_emits_nothing(self):
        self.assertEqual(watch.evaluate({"vol_30d_median": 8.1}, RULES["rules"][0]), None)


class DedupeTest(unittest.TestCase):
    """A threshold that stays crossed is one event, not one per poll."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.state = pathlib.Path(self.dir) / "seen.json"

    def test_repeat_crossing_suppressed(self):
        m = {"vol_20d": 11.2, "vol_30d_median": 8.1}
        first  = watch.emit_if_new(watch.evaluate(m, RULES["rules"][0]), self.state)
        second = watch.emit_if_new(watch.evaluate(m, RULES["rules"][0]), self.state)
        self.assertTrue(first)
        self.assertFalse(second, "a still-crossed threshold must not re-fire")

    def test_refires_after_reset(self):
        """Exercised through poll(), which is where re-arming actually happens."""
        out = pathlib.Path(self.dir) / "signals.jsonl"
        def cycle(vol):
            return watch.poll({"SPY": {"vol_20d": vol, "vol_30d_median": 8.1, "bars": bars()}},
                              RULES, NOW, out, self.state)
        self.assertEqual(cycle(11.2), 1, "first crossing fires")
        self.assertEqual(cycle(11.3), 0, "still crossed -> stays silent")
        self.assertEqual(cycle(8.0), 0, "reset below threshold -> silent, and re-arms")
        self.assertEqual(cycle(11.5), 1, "crosses again -> fires again")


class SilenceTest(unittest.TestCase):
    """Silence is the most common correct output."""

    def test_poll_with_nothing_crossing_writes_no_signal(self):
        d = tempfile.mkdtemp()
        out = pathlib.Path(d) / "signals.jsonl"
        n = watch.poll({"SPY": {"vol_20d": 8.0, "vol_30d_median": 8.1, "bars": bars()}},
                       RULES, NOW, out, pathlib.Path(d) / "seen.json")
        self.assertEqual(n, 0)
        self.assertFalse(out.exists())

    def test_closed_market_emits_nothing_even_when_crossed(self):
        d = tempfile.mkdtemp()
        out = pathlib.Path(d) / "signals.jsonl"
        n = watch.poll({"SPY": {"vol_20d": 99.0, "vol_30d_median": 8.1, "bars": bars()}},
                       RULES, datetime.datetime(2026, 8, 18, 3, 0), out, pathlib.Path(d)/"seen.json")
        self.assertEqual(n, 0)

    def test_insane_data_emits_nothing_even_when_crossed(self):
        d = tempfile.mkdtemp()
        out = pathlib.Path(d) / "signals.jsonl"
        n = watch.poll({"SPY": {"vol_20d": 99.0, "vol_30d_median": 8.1, "bars": bars(volume=0)}},
                       RULES, NOW, out, pathlib.Path(d) / "seen.json")
        self.assertEqual(n, 0, "zero-volume bars must never produce a signal")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class RelativeThresholdTest(unittest.TestCase):
    """Real data exposed this: an absolute vol threshold fires constantly because 'high vol'
    is only meaningful relative to what is normal FOR THAT SYMBOL. SPY at 13.6 against a 13.5
    median is not an event; QQQ at 24 against a 25 median is not an event either."""

    RULE = {"symbol": "SPY", "metric": "vol_20d", "op": "x>", "threshold": 1.5,
            "baseline": "vol_30d_median"}

    def test_normal_level_relative_to_its_own_baseline_is_silent(self):
        self.assertIsNone(watch.evaluate({"vol_20d": 13.64, "vol_30d_median": 13.52}, self.RULE))

    def test_genuine_spike_fires(self):
        sig = watch.evaluate({"vol_20d": 27.0, "vol_30d_median": 13.5}, self.RULE)
        self.assertIsNotNone(sig)
        self.assertIn("2.00x", sig["observed"])

    def test_just_under_the_multiple_is_silent(self):
        self.assertIsNone(watch.evaluate({"vol_20d": 20.0, "vol_30d_median": 13.5}, self.RULE))

    def test_missing_baseline_is_silent_not_an_error(self):
        self.assertIsNone(watch.evaluate({"vol_20d": 27.0}, self.RULE))

    def test_zero_baseline_does_not_divide_by_zero(self):
        self.assertIsNone(watch.evaluate({"vol_20d": 27.0, "vol_30d_median": 0.0}, self.RULE))


class TimezoneTest(unittest.TestCase):
    """Bug found by running it: market hours are ET, the code used local time. Correct by
    accident on an ET machine; wrong everywhere else, and wrong after travel."""

    def test_market_hours_are_evaluated_in_eastern_not_local(self):
        from zoneinfo import ZoneInfo
        # 09:00 Pacific = 12:00 Eastern -> market IS open, despite being before 09:30 locally
        pacific_9am = datetime.datetime(2026, 8, 19, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.assertTrue(watch.market_is_open(pacific_9am, RULES))

    def test_late_eastern_evening_is_closed_from_any_zone(self):
        from zoneinfo import ZoneInfo
        la = datetime.datetime(2026, 8, 19, 17, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        self.assertFalse(watch.market_is_open(la, RULES))  # 20:30 ET

    def test_naive_datetime_still_works(self):
        self.assertTrue(watch.market_is_open(datetime.datetime(2026, 8, 19, 11, 0), RULES))

    def test_weekend_in_eastern(self):
        self.assertFalse(watch.market_is_open(datetime.datetime(2026, 8, 22, 11, 0), RULES))


class ObservabilityTest(unittest.TestCase):
    """Bug found by running it: poll() returned 0 for BOTH 'market closed' and 'nothing
    crossed', and both logged 'quiet'. A dead feed during market hours looked identical to a
    calm afternoon — the single most dangerous kind of silence."""

    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())

    def test_closed_market_reports_closed_not_quiet(self):
        st = watch.poll_status({"SPY": {"vol_20d": 99.0, "vol_30d_median": 8.1, "bars": bars()}},
                               RULES, datetime.datetime(2026, 8, 18, 3, 0),
                               self.d / "s.jsonl", self.d / "seen.json")
        self.assertEqual(st["state"], "closed")

    def test_stale_or_broken_feed_is_reported_as_a_problem(self):
        st = watch.poll_status({"SPY": {"vol_20d": 99.0, "vol_30d_median": 8.1,
                                        "bars": bars(volume=0)}},
                               RULES, NOW, self.d / "s.jsonl", self.d / "seen.json")
        self.assertEqual(st["state"], "data-refused")
        self.assertTrue(st["problems"])

    def test_genuine_calm_is_reported_as_quiet(self):
        st = watch.poll_status({"SPY": {"vol_20d": 8.0, "vol_30d_median": 8.1, "bars": bars()}},
                               RULES, NOW, self.d / "s.jsonl", self.d / "seen.json")
        self.assertEqual(st["state"], "quiet")

    def test_a_signal_is_reported_as_such(self):
        st = watch.poll_status({"SPY": {"vol_20d": 99.0, "vol_30d_median": 8.1, "bars": bars()}},
                               RULES, NOW, self.d / "s.jsonl", self.d / "seen.json")
        self.assertEqual(st["state"], "signal")
        self.assertEqual(st["written"], 1)

    def test_no_symbol_data_at_all_is_not_reported_as_quiet(self):
        st = watch.poll_status({}, RULES, NOW, self.d / "s.jsonl", self.d / "seen.json")
        self.assertEqual(st["state"], "no-data")


class MetricPlausibilityTest(unittest.TestCase):
    """Found by attacking the feed: bars were sanity-checked, the COMPUTED METRICS were not.
    Infinity fired a signal. So did vol of 999999%, and a baseline crushed to 0.0001 producing
    a 136,500x ratio. A hostile or corrupted feed could manufacture a signal at will."""

    RULE = {"symbol": "SPY", "metric": "vol_20d", "op": "x>", "threshold": 1.5,
            "baseline": "vol_30d_median"}

    def fires(self, **m):
        return watch.evaluate(m, self.RULE) is not None

    def test_infinity_is_refused(self):
        self.assertFalse(self.fires(vol_20d=float("inf"), vol_30d_median=13.5))

    def test_nan_is_refused(self):
        self.assertFalse(self.fires(vol_20d=float("nan"), vol_30d_median=13.5))

    def test_absurd_metric_is_refused(self):
        self.assertFalse(self.fires(vol_20d=999999.0, vol_30d_median=13.5))

    def test_metric_above_the_plausible_ceiling_is_refused(self):
        self.assertFalse(self.fires(vol_20d=400.0, vol_30d_median=13.5),
                         "annualised vol of 400% is corrupt data, not an event")

    def test_baseline_below_the_floor_is_refused(self):
        self.assertFalse(self.fires(vol_20d=13.65, vol_30d_median=0.0001),
                         "a crushed baseline manufactures an arbitrary ratio")

    def test_negative_baseline_is_refused(self):
        self.assertFalse(self.fires(vol_20d=13.65, vol_30d_median=-5.0))

    def test_absurd_ratio_is_refused_even_with_plausible_parts(self):
        self.assertFalse(self.fires(vol_20d=180.0, vol_30d_median=1.2),
                         "150x is corrupt data, not a market event")

    def test_string_numbers_are_refused_not_coerced(self):
        self.assertFalse(self.fires(vol_20d="99", vol_30d_median=13.5),
                         "a typed feed must not silently coerce")

    # --- and the real signals must still get through ---
    def test_a_genuine_spike_still_fires(self):
        self.assertTrue(self.fires(vol_20d=33.8, vol_30d_median=13.52))

    def test_a_large_but_real_crisis_spike_still_fires(self):
        self.assertTrue(self.fires(vol_20d=75.0, vol_30d_median=14.0),
                        "March 2020 was real — do not clip genuine crises")

    def test_normal_conditions_stay_quiet(self):
        self.assertFalse(self.fires(vol_20d=13.65, vol_30d_median=13.52))
