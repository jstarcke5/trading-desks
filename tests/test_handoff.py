"""Typed handoffs. The contract is enforced by the tool, not by a document.

Core property: the Skeptic must receive the THESIS ARTIFACT, never the Analyst's reasoning.
If the Analyst can hand over its chain of thought, the Skeptic is captured by the argument and
the separation of powers collapses into agreement. Field caps are what make that structural.
"""
import os, sys, tempfile, unittest, pathlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "handoff"))
import relay  # noqa: E402

THESIS = {"TYPE": "THESIS", "symbol": "SPY", "claim": "vol mean-reverts from this level",
          "mechanism": "dealers short gamma must buy back", "horizon": "10d, stop 5%",
          "fee_in_R": "0.04", "evidence": "n=112, both halves positive",
          "falsifier": "two consecutive weeks of rising realised vol",
          "confidence": "0.55"}

class FlowTest(unittest.TestCase):
    def test_valid_edge_and_type_accepted(self):
        ok, why = relay.validate("analyst", "skeptic", THESIS)
        self.assertTrue(ok, why)

    def test_analyst_cannot_reach_executor(self):
        ok, why = relay.validate("analyst", "executor", THESIS)
        self.assertFalse(ok); self.assertIn("no route", why)

    def test_skeptic_cannot_send_an_order(self):
        order = {"TYPE": "ORDER", "symbol": "SPY", "side": "buy", "quantity": "1",
                 "limit_price": "10", "order_type": "limit", "asset_class": "equity",
                 "stop": "5%", "headroom": "12.00", "falsifier": "x"}
        ok, why = relay.validate("skeptic", "executor", order)
        self.assertFalse(ok); self.assertIn("no route", why)

    def test_wrong_artifact_type_on_a_real_edge_rejected(self):
        ok, why = relay.validate("analyst", "skeptic", {"TYPE": "ORDER"})
        self.assertFalse(ok); self.assertIn("expects THESIS", why)

    def test_executor_may_report_back_to_risk(self):
        ok, why = relay.validate("executor", "risk",
                                 {"TYPE": "RESULT", "status": "REFUSED", "detail": "over cap"})
        self.assertTrue(ok, why)


class SchemaTest(unittest.TestCase):
    def test_missing_falsifier_rejected(self):
        t = dict(THESIS); del t["falsifier"]
        ok, why = relay.validate("analyst", "skeptic", t)
        self.assertFalse(ok); self.assertIn("falsifier", why)

    def test_extra_field_rejected(self):
        t = dict(THESIS, my_reasoning="first I considered... then I realised...")
        ok, why = relay.validate("analyst", "skeptic", t)
        self.assertFalse(ok); self.assertIn("unknown", why)

    def test_empty_required_field_rejected(self):
        ok, why = relay.validate("analyst", "skeptic", dict(THESIS, falsifier="   "))
        self.assertFalse(ok); self.assertIn("falsifier", why)


class ProseSmugglingTest(unittest.TestCase):
    """The real attack: stuff the whole chain of thought into a legitimate field."""

    def test_oversized_field_rejected(self):
        ok, why = relay.validate("analyst", "skeptic",
                                 dict(THESIS, claim="reasoning. " * 400))
        self.assertFalse(ok); self.assertIn("too long", why)

    def test_many_newlines_rejected_as_prose(self):
        ok, why = relay.validate("analyst", "skeptic",
                                 dict(THESIS, mechanism="step1\nstep2\nstep3\nstep4\nstep5\nstep6"))
        self.assertFalse(ok); self.assertIn("single", why)

    def test_a_normal_one_line_claim_passes(self):
        ok, why = relay.validate("analyst", "skeptic", THESIS)
        self.assertTrue(ok, why)


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())

    def test_submit_then_recipient_reads_it(self):
        ok, _ = relay.submit("analyst", "skeptic", THESIS, self.root)
        self.assertTrue(ok)
        self.assertEqual(len(relay.inbox("skeptic", self.root)), 1)

    def test_inbox_is_isolated_between_desks(self):
        relay.submit("analyst", "skeptic", THESIS, self.root)
        self.assertEqual(relay.inbox("executor", self.root), [])
        self.assertEqual(relay.inbox("analyst", self.root), [])

    def test_rejected_submission_leaves_nothing_behind(self):
        relay.submit("analyst", "executor", THESIS, self.root)
        self.assertEqual(relay.inbox("executor", self.root), [])

    def test_delivered_artifact_carries_its_sender(self):
        relay.submit("analyst", "skeptic", THESIS, self.root)
        self.assertEqual(relay.inbox("skeptic", self.root)[0]["_from"], "analyst")

    def test_unknown_desk_name_refused(self):
        ok, why = relay.submit("analyst", "shadow-desk", THESIS, self.root)
        self.assertFalse(ok); self.assertIn("no route", why)


if __name__ == "__main__":
    unittest.main(verbosity=2)
