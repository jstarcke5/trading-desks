"""End-to-end acceptance over the real MCP wire protocol.

HANDOFF.md §5: "send it an order 10x the cap and confirm it is REFUSED, not filled.
A cap nobody has watched reject something is a comment, not a cap."
"""
import json, os, pathlib, subprocess, sys, unittest

def lim_cap():
    """Read the shipped exposure cap so this test tracks config rather than a hardcoded number."""
    d = json.loads((ROOT / "guardrail" / "limits.json").read_text())
    return float(d["max_open_exposure"])

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER = ROOT / "guardrail" / "server.py"

def rpc(mode, *messages):
    proc = subprocess.run([sys.executable, str(SERVER), "--mode", mode],
                          input="\n".join(json.dumps(m) for m in messages) + "\n",
                          capture_output=True, text=True, timeout=20,
                          env={**os.environ, "GUARDRAIL_UPSTREAM": "mock"})
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]

def call(mode, tool, args, rid=2):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
             "params": {"name": tool, "arguments": args}}]
    out = rpc(mode, *msgs)
    body = [r for r in out if r.get("id") == rid][0]
    return json.loads(body["result"]["content"][0]["text"]), body["result"]["isError"]

ORDER = {"symbol": "SPY", "side": "buy", "quantity": 1.0, "limit_price": 10.0,
         "order_type": "limit", "asset_class": "equity"}


class AcceptanceTest(unittest.TestCase):

    def test_THE_TEST_ten_times_the_cap_is_refused_not_filled(self):
        # limits.json caps a single order at $25. This asks for $250.
        payload, is_error = call("orders", "place_order", dict(ORDER, quantity=25.0))
        self.assertEqual(payload["status"], "REFUSED", payload)
        self.assertIn("max_order_notional", payload["reason"])
        self.assertTrue(is_error)
        self.assertNotIn("SIMULATED", json.dumps(payload))

    def test_a_compliant_order_is_accepted(self):
        payload, _ = call("orders", "place_order", ORDER)
        self.assertEqual(payload["status"], "SIMULATED", payload)
        self.assertIn("not transmitted", payload["detail"])

    def test_read_modes_cannot_reach_place_order(self):
        for mode in ("read-market", "read-portfolio"):
            payload, is_error = call(mode, "place_order", ORDER)
            self.assertIn("not available in mode", payload["error"])
            self.assertTrue(is_error)

    def test_tools_list_never_leaks_place_order_to_read_modes(self):
        for mode, expect in (("read-market", False), ("read-portfolio", False), ("orders", True)):
            out = rpc(mode, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            names = [t["name"] for t in [r for r in out if r.get("id") == 2][0]["result"]["tools"]]
            self.assertEqual("place_order" in names, expect, (mode, names))

    def test_options_refused_over_the_wire(self):
        payload, _ = call("orders", "place_order", dict(ORDER, asset_class="option"))
        self.assertEqual(payload["status"], "REFUSED")

    def test_unknown_symbol_refused_over_the_wire(self):
        payload, _ = call("orders", "place_order", dict(ORDER, symbol="GME"))
        self.assertEqual(payload["status"], "REFUSED")

    def test_the_test_suite_can_never_transmit(self):
        """This test exists because the suite was itself a live-order vector: a test setting
        GUARDRAIL_UPSTREAM=http would have transmitted once a real token existed. Arming is now
        a file on disk that no test creates."""
        import importlib, os as _os, sys as _sys
        _sys.path.insert(0, str(ROOT / "guardrail"))
        _live = importlib.import_module("live")
        import tempfile as _tf
        isolated = _tf.mkdtemp()
        self.assertFalse(_live.transmission_enabled(
            {"GUARDRAIL_UPSTREAM": "http"}, token="a-real-looking-token", here=isolated),
            "env + token alone must NOT be enough — the arming file is required")
        self.assertFalse(_live.armed(str(ROOT / "tests")),
                         "no arming file may exist in the test tree")
        # every subprocess this suite spawns must be explicitly non-transmitting
        self.assertEqual(os.environ.get("GUARDRAIL_UPSTREAM", "mock"), "mock",
                         "run the suite without GUARDRAIL_UPSTREAM=http exported")

    def test_nothing_transmits_with_the_switches_off(self):
        proc = subprocess.run([sys.executable, str(SERVER), "--mode", "orders"],
            input=json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}) + "\n" +
                  json.dumps({"jsonrpc":"2.0","id":2,"method":"tools/call",
                              "params":{"name":"place_order","arguments":ORDER}}) + "\n",
            capture_output=True, text=True, timeout=20,
            env={**{k: v for k, v in os.environ.items()
                    if k not in ("GUARDRAIL_UPSTREAM", "GUARDRAIL_UPSTREAM_TOKEN")}})
        body = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
        payload = json.loads([r for r in body if r.get("id") == 2][0]["result"]["content"][0]["text"])
        self.assertEqual(payload["status"], "SIMULATED", payload)
        self.assertIn("not transmitted", payload["detail"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class StateTrackingTest(unittest.TestCase):
    """A limit that reads state nothing maintains is a comment, not a limit."""

    def setUp(self):
        self.state = ROOT / "guardrail" / "state.json"
        if self.state.exists():
            self.state.unlink()

    tearDown = setUp

    def test_accepted_order_increments_daily_notional(self):
        call("orders", "place_order", dict(ORDER, quantity=2.0))          # $20
        s = json.loads(self.state.read_text())
        self.assertAlmostEqual(s["notional_today"], 20.0)
        self.assertAlmostEqual(s["open_exposure"], 20.0)

    def test_refused_order_does_not_move_state(self):
        call("orders", "place_order", dict(ORDER, quantity=25.0))         # refused
        self.assertFalse(self.state.exists(), "a refusal must not touch state")

    def test_accumulated_state_eventually_blocks_further_buying(self):
        """Repeated buys must eventually be refused by a size limit once accumulated state
        fills the exposure or daily cap -- whichever binds first."""
        for _ in range(int(lim_cap() // 20) + 1):
            call("orders", "place_order", dict(ORDER, quantity=2.0))
        payload, is_error = call("orders", "place_order", dict(ORDER, quantity=2.0))
        self.assertEqual(payload["status"], "REFUSED", payload)
        self.assertTrue(any(k in payload["reason"] for k in
                            ("max_open_exposure", "max_daily_notional")), payload["reason"])
        self.assertTrue(is_error)

    def test_buy_records_position_so_min_hold_can_bite(self):
        call("orders", "place_order", dict(ORDER, quantity=2.0))
        payload, _ = call("orders", "place_order", dict(ORDER, side="sell", quantity=1.0))
        self.assertEqual(payload["status"], "REFUSED", payload)
        self.assertIn("min_hold_minutes", payload["reason"])
