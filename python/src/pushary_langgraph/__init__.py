"""Human-in-the-loop for LangGraph and LangChain, powered by Pushary.

Two seams over the durable two-call contract (``enroll`` + ``decisions.ask``):

- ``ask_human`` / ``pushary_interrupt`` without a callback: a blocking approval you
  call from inside a node. It polls durably and fails closed.
- ``pushary_interrupt`` with a ``callback_url``: parks the graph with LangGraph's
  native ``interrupt()`` and resumes on Pushary's signed webhook, so an hour-long
  wait holds no compute and survives a restart.

Zero framework import at module load: LangGraph is imported lazily, only on the
durable path, so the blocking helpers work (and test) without it installed.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from pushary import (
    PusharyServer,
    SIGNATURE_HEADER,
    deterministic_key,
    is_approved,
    parse_decision_callback,
    verify_webhook_signature,
)

__version__ = "0.1.0"

__all__ = [
    "connect",
    "ask_human",
    "pushary_interrupt",
    "describe_answer",
    "resolve_pushary_callback",
    "is_affirmative",
    "deterministic_key",
    "SIGNATURE_HEADER",
    "__version__",
]


def _client(api_key: Optional[str] = None, base_url: Optional[str] = None) -> PusharyServer:
    key = api_key or os.environ.get("PUSHARY_API_KEY")
    if not key:
        raise ValueError("Pushary: set PUSHARY_API_KEY or pass api_key=... to the LangGraph helpers.")
    return PusharyServer(api_key=key, base_url=base_url)


def _idempotency_key(external_id: str, node: str, question: str) -> str:
    return deterministic_key([external_id, node, question])


def is_affirmative(answer: Optional[str]) -> bool:
    """Fail-closed yes/no check for a confirm answer."""
    return is_approved("answered", "confirm", answer)


def connect(external_id: str, *, api_key: Optional[str] = None, base_url: Optional[str] = None) -> str:
    """Connect one end-user's phone (keyless). Returns a single-use link to show them."""
    return _client(api_key, base_url).enroll(external_id)["universalLink"]


def ask_human(
    question: str,
    *,
    external_id: str,
    type: str = "confirm",
    options: Optional[List[str]] = None,
    node: str = "ask-human",
    context: Optional[str] = None,
    agent_name: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Blocking ask (Pattern A): create a decision and poll durably until answered.

    Returns the decision dict (``decisionId``, ``status``, ``answered``, ``value``,
    ``type``, fail-closed ``approved``). The idempotency key is derived from
    external_id + node + question, so a node that re-runs on resume hits the same
    decision instead of paging the human twice.
    """
    return _client(api_key, base_url).decisions.ask(
        question,
        type=type,
        options=options,
        external_id=external_id,
        context=context,
        agent_name=agent_name,
        timeout_seconds=timeout_seconds,
        idempotency_key=_idempotency_key(external_id, node, question),
    )


def describe_answer(type: str, result: Dict[str, Any]) -> str:
    """Turn a decision outcome into an unambiguous instruction for the model."""
    if not result.get("answered"):
        return (
            f"No answer (status: {result.get('status')}). "
            "Treat this as NOT approved and do not proceed."
        )
    if type == "confirm":
        return (
            "The human approved. You may proceed."
            if result.get("approved")
            else "The human declined. Do not proceed."
        )
    return f"The human answered: {result.get('value') or ''}"


def resolve_pushary_callback(
    raw_body: Any, signature: Optional[str], secret: str
) -> Optional[Dict[str, Any]]:
    """Verify a callback signature and parse it, or return None.

    Feed ``answer`` into ``graph.invoke(Command(resume=answer), config)``.
    """
    if not verify_webhook_signature(raw_body, signature, secret):
        return None
    cb = parse_decision_callback(raw_body)
    if not cb:
        return None
    return {
        "correlationId": cb.get("correlationId"),
        "answer": cb.get("answer"),
        "value": cb.get("value"),
        "approved": is_affirmative(cb.get("answer")),
        "context": cb.get("context"),
        "answeredAt": cb.get("answeredAt"),
    }


def pushary_interrupt(
    question: str,
    *,
    external_id: str,
    node: str = "hitl",
    type: str = "confirm",
    options: Optional[List[str]] = None,
    callback_url: Optional[str] = None,
    context: Optional[str] = None,
    agent_name: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[str]:
    """Ask a human from inside a LangGraph node.

    - ``callback_url`` omitted (Pattern A): blocks, polls durably, returns the answer
      (or None if fail-closed). Zero extra infra, holds the run open for the wait.
    - ``callback_url`` set (Pattern B): opens the decision, then calls LangGraph's
      ``interrupt()`` to park the graph in your checkpointer. Resume with
      ``Command(resume=answer)`` from the signed webhook. Holds no idle compute.

    The whole node re-runs on resume, so keep code before this call idempotent. The
    decision's idempotency key is derived from external_id + node + question, so the
    re-run lands on the same decision.
    """
    idem = _idempotency_key(external_id, node, question)
    px = _client(api_key, base_url)

    if not callback_url:
        d = px.decisions.ask(
            question,
            type=type,
            options=options,
            external_id=external_id,
            context=context,
            agent_name=agent_name,
            timeout_seconds=timeout_seconds,
            idempotency_key=idem,
        )
        return d.get("value") if d.get("answered") else None

    px.decisions.create(
        question,
        type=type,
        options=options,
        external_id=external_id,
        context=context,
        agent_name=agent_name,
        callback_url=callback_url,
        idempotency_key=idem,
        wait=False,
    )
    # Lazy import: only the durable path needs LangGraph installed.
    from langgraph.types import interrupt

    return interrupt({"pushary": "decision", "question": question, "external_id": external_id})
