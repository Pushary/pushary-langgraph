"""Tests for pushary_langgraph. Framework-free: LangGraph is never imported here,
so the blocking helpers are exercised without it installed. HTTP is mocked by
swapping the kernel's client constructor for a stub.
"""

import hashlib
import hmac
import json
import os
import unittest

import pushary_langgraph as plg
from pushary import adapters


class FakeDecisions:
    def __init__(self, ask_result=None, create_result=None):
        self.ask_calls = []
        self.create_calls = []
        self._ask_result = ask_result or {}
        self._create_result = create_result or {}

    def ask(self, question, **kwargs):
        self.ask_calls.append({"question": question, **kwargs})
        return self._ask_result

    def create(self, question, **kwargs):
        self.create_calls.append({"question": question, **kwargs})
        return self._create_result


class FakeClient:
    def __init__(self, decisions=None, enroll_result=None):
        self.decisions = decisions or FakeDecisions()
        self._enroll_result = enroll_result or {}
        self.enroll_calls = []

    def enroll(self, external_id):
        self.enroll_calls.append(external_id)
        return self._enroll_result


class WithFakeClient:
    """Patch the kernel's client constructor to a FakeClient for one test."""

    def __init__(self, client):
        self.client = client
        self._orig = None
        self._orig_key = None

    def __enter__(self):
        self._orig = adapters.PusharyServer
        adapters.PusharyServer = lambda **kwargs: self.client
        self._orig_key = os.environ.get("PUSHARY_API_KEY")
        os.environ["PUSHARY_API_KEY"] = "pk_test.sk_test"
        return self.client

    def __exit__(self, *exc):
        adapters.PusharyServer = self._orig
        if self._orig_key is None:
            os.environ.pop("PUSHARY_API_KEY", None)
        else:
            os.environ["PUSHARY_API_KEY"] = self._orig_key


SECRET = "whsec_test"


def sign(body: str) -> str:
    return hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


class ConnectTests(unittest.TestCase):
    def test_connect_returns_universal_link(self):
        client = FakeClient(enroll_result={"universalLink": "https://pushary.com/e/tok"})
        with WithFakeClient(client):
            link = plg.connect("user_1")
        self.assertEqual(link, "https://pushary.com/e/tok")
        self.assertEqual(client.enroll_calls, ["user_1"])


class AskHumanTests(unittest.TestCase):
    def test_ask_human_forwards_deterministic_idempotency_key(self):
        decisions = FakeDecisions(ask_result={"status": "answered", "answered": True, "value": "yes", "approved": True})
        with WithFakeClient(FakeClient(decisions=decisions)):
            out = plg.ask_human("Approve?", external_id="user_1", node="approval")
        self.assertTrue(out["approved"])
        call = decisions.ask_calls[0]
        self.assertEqual(call["external_id"], "user_1")
        self.assertTrue(call["idempotency_key"])
        # same input -> same key (re-run safe)
        expected = plg.deterministic_key(["user_1", "approval", "Approve?"])
        self.assertEqual(call["idempotency_key"], expected)


class PusharyInterruptTests(unittest.TestCase):
    def test_blocking_pattern_returns_value_when_answered(self):
        decisions = FakeDecisions(ask_result={"answered": True, "value": "yes"})
        with WithFakeClient(FakeClient(decisions=decisions)):
            answer = plg.pushary_interrupt("Approve?", external_id="user_1", node="n")
        self.assertEqual(answer, "yes")

    def test_blocking_pattern_fails_closed_when_unanswered(self):
        decisions = FakeDecisions(ask_result={"answered": False, "status": "expired"})
        with WithFakeClient(FakeClient(decisions=decisions)):
            answer = plg.pushary_interrupt("Approve?", external_id="user_1", node="n")
        self.assertIsNone(answer)

    def test_durable_pattern_opens_decision_with_callback(self):
        # callback_url set -> Pattern B calls create() then imports langgraph.interrupt.
        # langgraph is not installed in this test env, so we assert the create call happened
        # and that the lazy import is what raises (not our code path).
        decisions = FakeDecisions(create_result={"decisionId": "d1", "status": "pending"})
        with WithFakeClient(FakeClient(decisions=decisions)):
            with self.assertRaises(ImportError):
                plg.pushary_interrupt(
                    "Approve?", external_id="user_1", node="n", callback_url="https://x/cb"
                )
        create = decisions.create_calls[0]
        self.assertEqual(create["callback_url"], "https://x/cb")
        self.assertEqual(create["wait"], False)


class DescribeAnswerTests(unittest.TestCase):
    def test_formats_every_outcome(self):
        self.assertIn("approved", plg.describe_answer("confirm", {"answered": True, "approved": True}))
        self.assertIn("declined", plg.describe_answer("confirm", {"answered": True, "approved": False}))
        self.assertIn("NOT approved", plg.describe_answer("confirm", {"answered": False, "status": "expired"}))
        self.assertIn("B", plg.describe_answer("select", {"answered": True, "value": "B"}))


class ResolveCallbackTests(unittest.TestCase):
    def test_verifies_parses_and_folds_approved(self):
        body = json.dumps({"correlationId": "d1", "answer": "yes", "answeredAt": "", "context": "t-1"})
        out = plg.resolve_pushary_callback(body, sign(body), SECRET)
        self.assertEqual(out["correlationId"], "d1")
        self.assertTrue(out["approved"])
        self.assertEqual(out["context"], "t-1")

    def test_rejects_bad_signature(self):
        body = json.dumps({"correlationId": "d1", "answer": "yes", "answeredAt": ""})
        self.assertIsNone(plg.resolve_pushary_callback(body, "nope", SECRET))

    def test_decline_is_not_approved(self):
        body = json.dumps({"correlationId": "d2", "answer": "no", "answeredAt": ""})
        out = plg.resolve_pushary_callback(body, sign(body), SECRET)
        self.assertFalse(out["approved"])


class IsAffirmativeTests(unittest.TestCase):
    def test_fail_closed(self):
        self.assertTrue(plg.is_affirmative("yes"))
        self.assertFalse(plg.is_affirmative("no"))
        self.assertFalse(plg.is_affirmative(None))


if __name__ == "__main__":
    unittest.main()
