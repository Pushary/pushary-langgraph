"""Human-in-the-loop for LangGraph and LangChain, powered by Pushary.

Two seams over the durable two-call contract (``enroll`` + ``decisions.ask``):

- ``ask_human`` / ``pushary_interrupt`` without a callback: a blocking approval you
  call from inside a node. It polls durably and fails closed.
- ``pushary_interrupt`` with a ``callback_url``: parks the graph with LangGraph's
  native ``interrupt()`` and resumes on Pushary's signed webhook, so an hour-long
  wait holds no compute and survives a restart.

Everything but the LangGraph binding is the shared kernel from ``pushary.adapters``,
bound to this adapter's name.

Zero framework import at module load: LangGraph is imported lazily, only on the
durable path, so the blocking helpers work (and test) without it installed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pushary import SIGNATURE_HEADER, deterministic_key
from pushary.adapters import (
    AdapterKernel,
    ApprovalAsk,
    ApprovalDecision,
    describe_answer,
    is_affirmative,
    render_approval_question,
    resolve_pushary_callback,
)

__version__ = "0.2.0"

__all__ = [
    "connect",
    "ask_human",
    "pushary_interrupt",
    "describe_answer",
    "resolve_pushary_callback",
    "is_affirmative",
    "render_approval_question",
    "deterministic_key",
    "create_pushary_gate",
    "require_pushary_external_id",
    "ApprovalAsk",
    "ApprovalDecision",
    "SIGNATURE_HEADER",
    "__version__",
]

_kernel = AdapterKernel("the LangGraph helpers")

connect = _kernel.connect
ask_human = _kernel.ask_human

#: Build a request-time approval gate bound to these helpers.
create_pushary_gate = _kernel.create_gate

#: The end-user to ask, or a clear error naming these helpers.
require_pushary_external_id = _kernel.require_external_id


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

    if not callback_url:
        decision: Dict[str, Any] = ask_human(
            question,
            external_id=external_id,
            type=type,
            options=options,
            node=node,
            context=context,
            agent_name=agent_name,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
            base_url=base_url,
        )
        return decision.get("value") if decision.get("answered") else None

    _kernel.create_durable_decision(
        question,
        external_id=external_id,
        callback_url=callback_url,
        type=type,
        options=options,
        node=node,
        context=context,
        agent_name=agent_name,
        api_key=api_key,
        base_url=base_url,
    )
    # Lazy import: only the durable path needs LangGraph installed.
    from langgraph.types import interrupt

    return interrupt({"pushary": "decision", "question": question, "external_id": external_id})
