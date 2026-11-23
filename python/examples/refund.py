"""Run an order through a real LangGraph with a simulated Pushary reply."""
from typing import TypedDict
from unittest.mock import patch

from langgraph.graph import END, START, StateGraph
from pushary_langgraph import pushary_interrupt


class Order(TypedDict):
    order_id: str
    approved: bool
    refunds: int


def review(order: Order) -> dict:
    answer = pushary_interrupt(
        "Refund $40 for this order?",
        external_id="demo-customer",
        tool_target=order["order_id"],
        idempotency_key=f"review-{order['order_id']}",
        api_key="pk_demo.sk_demo",
    )
    return {"approved": answer == "yes"}


def refund(order: Order) -> dict:
    return {"refunds": order["refunds"] + 1}


workflow = StateGraph(Order)
workflow.add_node("review", review)
workflow.add_node("refund", refund)
workflow.add_edge(START, "review")
workflow.add_conditional_edges("review", lambda order: "refund" if order["approved"] else END)
workflow.add_edge("refund", END)
graph = workflow.compile()

for reply in ("yes", "no", None):
    with patch("pushary.adapters.PusharyServer") as server:
        ask = server.return_value.decisions.ask
        ask.return_value = {
            "type": "confirm", "status": "answered" if reply else "expired",
            "answered": reply is not None, "value": reply,
        }
        result = graph.invoke({"order_id": f"demo-{reply}", "approved": False, "refunds": 0})
        ask.assert_called_once()
        assert result["refunds"] == int(reply == "yes")
        print(f"{reply or 'unanswered'} → simulated refunds: {result['refunds']}")
