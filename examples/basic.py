"""Minimal LangGraph (Python) example: ask a human inside a node.

Prereqs: pip install pushary-langgraph
Run:     PUSHARY_API_KEY=... python examples/basic.py
"""
from pushary_langgraph import ask_human, connect

USER_ID = "user_123"


def main() -> None:
    # 1) One time per end-user: connect their phone.
    link = connect(USER_ID)
    print("Ask the user to open:", link)

    # 2) Ask a real human, block, fail-closed.
    decision = ask_human("Approve a $40 refund?", external_id=USER_ID, node="approval")
    print("approved:", decision["approved"])


if __name__ == "__main__":
    main()
