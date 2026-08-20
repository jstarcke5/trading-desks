"""Account pinning. The token can see every account the user owns — including their main
brokerage account and their Roth IRA. Robinhood flags those agentic_allowed=false, but relying
on someone else's check is the mistake this whole project exists to avoid. We pin one account
and refuse everything else, on our side, before any request leaves the machine."""
import os, sys, tempfile, unittest, pathlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import account  # noqa: E402

AGENTIC = {"account_number": "YOUR_AGENTIC_ACCOUNT", "brokerage_account_type": "individual",
           "nickname": "Agentic", "agentic_allowed": True, "type": "cash"}
MAIN    = {"account_number": "111111111", "brokerage_account_type": "individual",
           "agentic_allowed": False, "is_default": True, "type": "margin"}
ROTH    = {"account_number": "222222222", "brokerage_account_type": "ira_roth",
           "agentic_allowed": False, "type": "cash"}


class PinSelectionTest(unittest.TestCase):
    def test_picks_the_only_agentic_account(self):
        self.assertEqual(account.choose([MAIN, ROTH, AGENTIC])["account_number"], "YOUR_AGENTIC_ACCOUNT")

    def test_refuses_when_no_agentic_account_exists(self):
        with self.assertRaises(account.NoAgenticAccount):
            account.choose([MAIN, ROTH])

    def test_refuses_to_pin_a_non_agentic_account(self):
        with self.assertRaises(ValueError):
            account.validate_pinnable(MAIN)
        with self.assertRaises(ValueError):
            account.validate_pinnable(ROTH)

    def test_refuses_ambiguity_rather_than_guessing(self):
        second = dict(AGENTIC, account_number="999999999")
        with self.assertRaises(account.AmbiguousAccount):
            account.choose([AGENTIC, second])

    def test_refuses_a_deactivated_agentic_account(self):
        with self.assertRaises(ValueError):
            account.validate_pinnable(dict(AGENTIC, deactivated=True))

    def test_refuses_a_margin_agentic_account(self):
        """Leverage was measured to destroy risk-adjusted returns. Cash only."""
        with self.assertRaises(ValueError):
            account.validate_pinnable(dict(AGENTIC, type="margin"))


class ReadWriteSplitTest(unittest.TestCase):
    """Policy: READ any account the user owns. WRITE only the pinned agentic account."""

    def setUp(self):
        self.path = pathlib.Path(tempfile.mkdtemp()) / "account.json"
        account.pin(AGENTIC, self.path)

    def test_reading_the_main_account_is_allowed(self):
        args, why = account.enforce("get_equity_positions",
                                   {"account_number": "111111111"}, self.path)
        self.assertIsNotNone(args, why)

    def test_reading_the_roth_ira_is_allowed(self):
        args, why = account.enforce("get_portfolio", {"account_number": "222222222"}, self.path)
        self.assertIsNotNone(args, why)

    def test_reading_with_no_account_does_not_get_pinned_injected(self):
        args, _ = account.enforce("get_accounts", {}, self.path)
        self.assertNotIn("account_number", args, "a read must not be silently narrowed")

    def test_ORDERING_on_the_main_account_is_refused(self):
        args, why = account.enforce("place_equity_order",
                                   {"account_number": "111111111"}, self.path)
        self.assertIsNone(args); self.assertIn("not the pinned", why)

    def test_ORDERING_on_the_roth_ira_is_refused(self):
        args, why = account.enforce("place_equity_order",
                                   {"account_number": "222222222"}, self.path)
        self.assertIsNone(args); self.assertIn("not the pinned", why)

    def test_ordering_on_the_agentic_account_is_allowed(self):
        args, why = account.enforce("place_equity_order",
                                   {"account_number": "YOUR_AGENTIC_ACCOUNT"}, self.path)
        self.assertIsNotNone(args, why)

    def test_order_with_no_account_gets_the_pin_injected(self):
        args, _ = account.enforce("place_equity_order", {"symbol": "SPY"}, self.path)
        self.assertEqual(args["account_number"], "YOUR_AGENTIC_ACCOUNT")

    def test_cancelling_an_order_on_another_account_is_refused(self):
        args, why = account.enforce("cancel_equity_order",
                                   {"account_number": "111111111"}, self.path)
        self.assertIsNone(args)

    def test_write_is_refused_when_nothing_is_pinned(self):
        empty = pathlib.Path(tempfile.mkdtemp()) / "none.json"
        args, why = account.enforce("place_equity_order", {"symbol": "SPY"}, empty)
        self.assertIsNone(args); self.assertIn("no account pinned", why)

    def test_nested_account_in_a_write_is_still_caught(self):
        args, why = account.enforce("place_equity_order",
                                   {"orders": [{"account_number": "111111111"}]}, self.path)
        self.assertIsNone(args)


class EnforcementTest(unittest.TestCase):
    def setUp(self):
        self.path = pathlib.Path(tempfile.mkdtemp()) / "account.json"
        account.pin(AGENTIC, self.path)

    def test_write_set_is_explicit(self):
        self.assertIn("place_equity_order", account.WRITE_TOOLS)
        self.assertIn("cancel_equity_order", account.WRITE_TOOLS)
        self.assertNotIn("get_portfolio", account.WRITE_TOOLS)


class ForbiddenToolTest(unittest.TestCase):
    """Options were never in scope, and exercise/transfer are irreversible."""

    def test_option_tools_are_forbidden(self):
        for t in ("place_option_order", "exercise_option", "cancel_option_exercise"):
            self.assertFalse(account.tool_permitted(t), t)

    def test_equity_read_and_review_are_permitted(self):
        for t in ("get_equity_quotes", "get_equity_positions", "review_equity_order",
                  "get_portfolio", "get_accounts", "get_equity_historicals"):
            self.assertTrue(account.tool_permitted(t), t)

    def test_place_equity_order_is_permitted_only_through_the_guardrail(self):
        self.assertTrue(account.tool_permitted("place_equity_order"))

    def test_unknown_tool_is_refused_by_default(self):
        self.assertFalse(account.tool_permitted("some_new_tool_robinhood_added"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
