import os
import tempfile
import unittest
from typing import Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pushary_langgraph import pushary_interrupt
from pushary_langgraph.review import ReviewRequest, parse_resume
from test_langgraph import FakeClient, FakeDecisions, WithFakeClient


class State(TypedDict):
    answer: Optional[str]


class RestartTests(unittest.TestCase):
    def test_sqlite_reopen_resumes_each_native_answer_without_a_new_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            for kind, answer in [("confirm", "yes"), ("confirm", "no"), ("select", "B"), ("input", "Dock 2")]:
                with self.subTest(kind=kind, answer=answer):
                    decisions = FakeDecisions(create_result={"decisionId": "decision-1", "status": "pending"})
                    def build(saver):
                        def review(_state):
                            return {"answer": pushary_interrupt(
                                "Review order", external_id="customer", type=kind,
                                options=["A", "B"] if kind == "select" else None,
                                idempotency_key="order-1", parameters={"revision": 1},
                                callback_url="https://test.invalid/callback",
                            )}
                        return StateGraph(State).add_node("review", review).add_edge(START, "review").add_edge("review", END).compile(checkpointer=saver)
                    path = os.path.join(directory, f"{kind}-{answer}.sqlite")
                    thread = {"configurable": {"thread_id": "customer-thread"}}
                    with WithFakeClient(FakeClient(decisions=decisions)):
                        with SqliteSaver.from_conn_string(path) as saver:
                            first = build(saver).invoke({}, thread)
                            pending = first["__interrupt__"][0]
                            self.assertEqual(pending.value["correlationId"], "decision-1")
                            self.assertEqual(pending.value["type"], kind)
                        with SqliteSaver.from_conn_string(path) as reopened:
                            graph = build(reopened)
                            result = graph.invoke(Command(resume={pending.id: {"correlationId": "decision-1", "answer": answer}}), thread)
                            self.assertEqual(result["answer"], answer)
                            self.assertEqual(graph.get_state(thread).next, ())
                    self.assertEqual(len({call["idempotency_key"] for call in decisions.create_calls}), 1)
                    self.assertEqual(decisions.create_calls[-1]["parameters"], {"revision": 1})

    def test_terminal_decision_replay_returns_no_approval(self):
        for status in ["expired", "cancelled"]:
            with self.subTest(status=status):
                decisions = FakeDecisions(create_result={"decisionId": "decision-1", "status": status})
                with WithFakeClient(FakeClient(decisions=decisions)):
                    self.assertIsNone(pushary_interrupt(
                        "Approve?", external_id="customer", idempotency_key="order-1",
                        callback_url="https://test.invalid/callback",
                    ))

    def test_preserves_opaque_identity_and_rejects_invalid_recipient_before_http(self):
        decisions = FakeDecisions(create_result={"decisionId": "decision-1", "status": "expired"})
        with WithFakeClient(FakeClient(decisions=decisions)):
            for key in [" operation ", "operation"]:
                pushary_interrupt("Approve?", external_id=" customer ", idempotency_key=key, callback_url="https://test.invalid/callback")
            self.assertEqual([call["external_id"] for call in decisions.create_calls], [" customer ", " customer "])
            self.assertNotEqual(decisions.create_calls[0]["idempotency_key"], decisions.create_calls[1]["idempotency_key"])
            pushary_interrupt("Approve?", external_id="😀" * 128, idempotency_key="operation", callback_url="https://test.invalid/callback")
            for recipient in [" ", "a" * 257, "😀" * 129]:
                with self.assertRaises(ValueError):
                    pushary_interrupt("Approve?", external_id=recipient, idempotency_key="operation", callback_url="https://test.invalid/callback")
            with self.assertRaises(ValueError):
                pushary_interrupt("Approve?", external_id="customer", idempotency_key=" ")
        self.assertEqual(len(decisions.create_calls), 3)
        self.assertEqual(decisions.ask_calls, [])

    def test_resume_validation_and_trusted_identity(self):
        review = ReviewRequest(question="Approve?", external_id="customer", callback_url="https://test.invalid/cb", idempotency_key="order-1", parameters={"revision": 1})
        original = review.bound_input()["idempotency_key"]
        self.assertEqual(review.bound_input()["idempotency_key"], original)
        for changed in [{"external_id": "other"}, {"parameters": {"revision": 2}}]:
            self.assertNotEqual(ReviewRequest(**(review.model_dump() | changed)).bound_input()["idempotency_key"], original)
        for value in ["yes", True, {}, {"correlationId": "wrong", "answer": "yes"}, {"correlationId": "d", "answer": {"approved": True}}, {"correlationId": "d", "answer": "anything"}]:
            with self.assertRaises(ValueError):
                parse_resume(value, "d", review)
        self.assertIsNone(parse_resume({"correlationId": "d", "answer": None, "status": "expired"}, "d", review))
        with self.assertRaises(ValueError):
            parse_resume({"correlationId": "d", "answer": "yes", "status": "expired"}, "d", review)


if __name__ == "__main__":
    unittest.main()
