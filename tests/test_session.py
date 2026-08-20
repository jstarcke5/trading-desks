"""Timeboxed session: trade within a window, and be FLAT before it closes.

The hard part is a conflict the mandate creates with itself. min_hold_minutes forbids selling
too soon after buying. If entries are allowed right up to the end, a position bought at 11:29
cannot legally be sold by 11:30 -- the system would be required to break one of its own rules
to obey the other. So entries must stop early enough that everything opened can still be
closed: last_entry = end - min_hold.
"""
import datetime, os, sys, unittest
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import session  # noqa: E402

ET = ZoneInfo("America/New_York")
def et(h, m): return datetime.datetime(2026, 8, 19, h, m, tzinfo=ET)

WINDOW = {"start": "09:30", "end": "11:30", "min_hold_minutes": 60, "flatten_buffer_minutes": 10}


class PhaseTest(unittest.TestCase):
    def test_before_start_is_closed(self):
        self.assertEqual(session.phase(et(9, 15), WINDOW), "before")

    def test_early_window_allows_entries(self):
        self.assertEqual(session.phase(et(9, 45), WINDOW), "open")

    def test_after_last_entry_it_is_exit_only(self):
        # end 11:30 - min_hold 60 = 10:30 last entry
        self.assertEqual(session.phase(et(10, 45), WINDOW), "exit-only")

    def test_inside_the_flatten_buffer_it_is_flattening(self):
        self.assertEqual(session.phase(et(11, 25), WINDOW), "flatten")

    def test_after_end_is_over(self):
        self.assertEqual(session.phase(et(11, 31), WINDOW), "over")

    def test_the_boundary_minute_is_still_over(self):
        self.assertEqual(session.phase(et(11, 30), WINDOW), "over")


class PermissionTest(unittest.TestCase):
    def allow(self, side, now):
        return session.may_trade(side, now, WINDOW)

    def test_buys_allowed_early(self):
        self.assertTrue(self.allow("buy", et(9, 45))[0])

    def test_buys_refused_once_they_could_not_be_exited_in_time(self):
        ok, why = self.allow("buy", et(10, 31))
        self.assertFalse(ok)
        self.assertIn("could not be exited", why)

    def test_sells_still_allowed_in_exit_only(self):
        self.assertTrue(self.allow("sell", et(10, 45))[0])

    def test_sells_allowed_during_flatten(self):
        self.assertTrue(self.allow("sell", et(11, 25))[0])

    def test_buys_refused_during_flatten(self):
        self.assertFalse(self.allow("buy", et(11, 25))[0])

    def test_everything_refused_after_the_end(self):
        for side in ("buy", "sell"):
            ok, why = self.allow(side, et(11, 31))
            self.assertFalse(ok, side)
            self.assertIn("session is over", why)

    def test_everything_refused_before_the_start(self):
        self.assertFalse(self.allow("buy", et(9, 15))[0])


class FlattenTest(unittest.TestCase):
    def test_open_positions_at_flatten_time_are_reported(self):
        state = {"positions": {"SPY": {"quantity": 2.0, "opened_at": "2026-08-19T09:40:00"}}}
        todo = session.flatten_plan(state, et(11, 25), WINDOW)
        self.assertEqual(len(todo), 1)
        self.assertEqual(todo[0]["side"], "sell")
        self.assertEqual(todo[0]["symbol"], "SPY")

    def test_nothing_to_flatten_when_already_flat(self):
        self.assertEqual(session.flatten_plan({"positions": {}}, et(11, 25), WINDOW), [])

    def test_no_flatten_plan_before_the_buffer(self):
        state = {"positions": {"SPY": {"quantity": 2.0, "opened_at": "2026-08-19T09:40:00"}}}
        self.assertEqual(session.flatten_plan(state, et(10, 0), WINDOW), [])


class SelfConsistencyTest(unittest.TestCase):
    """The window must never require breaking min_hold to obey the flatten mandate."""

    def test_a_position_opened_at_the_last_entry_can_still_be_held_the_minimum(self):
        last = session.last_entry_time(et(9, 30), WINDOW)
        end = session.end_time(et(9, 30), WINDOW)
        held = (end - last).total_seconds() / 60.0
        self.assertGreaterEqual(held, WINDOW["min_hold_minutes"])

    def test_a_window_shorter_than_min_hold_is_rejected_outright(self):
        bad = dict(WINDOW, end="10:00")          # 30 min window, 60 min min_hold
        with self.assertRaises(ValueError):
            session.validate(bad)

    def test_a_valid_window_passes_validation(self):
        self.assertTrue(session.validate(WINDOW))


if __name__ == "__main__":
    unittest.main(verbosity=2)
