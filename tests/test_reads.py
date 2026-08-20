"""Read passthrough. Found as a stub: every read tool returned SIMULATED and never called the
broker, so Risk would have sized against numbers it did not have."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guardrail"))
import reads, account  # noqa: E402


class MappingTest(unittest.TestCase):
    def test_every_read_tool_maps_to_a_real_broker_tool(self):
        for local in ("get_quote", "get_bars", "get_positions", "get_account", "market_clock"):
            self.assertIsNotNone(reads.BROKER_TOOL.get(local), local)

    def test_mapped_targets_are_all_on_the_account_allowlist(self):
        for target in reads.BROKER_TOOL.values():
            self.assertTrue(account.tool_permitted(target), target)

    def test_no_read_maps_to_an_order_placing_tool(self):
        for target in reads.BROKER_TOOL.values():
            self.assertNotIn("place_", target)
            self.assertFalse(account.is_write(target), target)

    def test_unknown_read_tool_is_refused(self):
        self.assertIsNone(reads.BROKER_TOOL.get("drain_the_account"))


class ArgumentTest(unittest.TestCase):
    def test_quote_symbols_are_normalised_to_a_list(self):
        a = reads.build_args("get_quote", {"symbol": "SPY"}, "YOUR_AGENTIC_ACCOUNT")
        self.assertEqual(a["symbols"], ["SPY"])

    def test_positions_carry_an_account(self):
        a = reads.build_args("get_positions", {}, "YOUR_AGENTIC_ACCOUNT")
        self.assertEqual(a["account_number"], "YOUR_AGENTIC_ACCOUNT")

    def test_reads_may_target_another_account(self):
        """Policy: read anywhere, write only the pinned account."""
        a = reads.build_args("get_positions", {"account_number": "111111111"}, "YOUR_AGENTIC_ACCOUNT")
        self.assertEqual(a["account_number"], "111111111")

    def test_symbols_are_uppercased(self):
        self.assertEqual(reads.build_args("get_quote", {"symbol": "spy"}, "x")["symbols"], ["SPY"])

    def test_empty_symbol_is_refused(self):
        with self.assertRaises(ValueError):
            reads.build_args("get_quote", {}, "YOUR_AGENTIC_ACCOUNT")


class FailClosedTest(unittest.TestCase):
    def test_no_token_means_simulated_not_silence(self):
        out = reads.execute("get_quote", {"symbol": "SPY"}, "YOUR_AGENTIC_ACCOUNT", token=None)
        self.assertEqual(out["status"], "SIMULATED")
        self.assertIn("no broker token", out["detail"])

    def test_unknown_tool_is_an_error_not_a_passthrough(self):
        out = reads.execute("wire_transfer", {}, "YOUR_AGENTIC_ACCOUNT", token="t")
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
