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

from typing import Any, Dict, List, Literal, Optional

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

from .review import CreatedDecision, ReviewRequest, ReviewResume, parse_answer, parse_resume

__version__ = "0.4.0"

__all__ = [
    "ReviewResume",
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
    idempotency_key: Optional[str] = None,
    type: Literal["confirm", "select", "input"] = "confirm",
    options: Optional[List[str]] = None,
    callback_url: Optional[str] = None,
    context: Optional[str] = None,
    agent_name: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    tool_target: Optional[str] = None,
    actor: Optional[str] = None,
    environment: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    presentation: Optional[Dict[str, Any]] = None,
    placeholder: Optional[str] = None,
    expires_in_seconds: Optional[int] = None,
    require_reachable: Optional[bool] = None,
) -> Optional[str]:
    review = ReviewRequest(
        question=question, external_id=external_id, node=node, idempotency_key=idempotency_key,
        type=type, options=options, callback_url=callback_url, context=context, agent_name=agent_name,
        tool_target=tool_target, actor=actor, environment=environment, parameters=parameters,
        presentation=presentation, placeholder=placeholder, expires_in_seconds=expires_in_seconds,
        require_reachable=require_reachable,
    )
    values = review.bound_input()
    values.pop("question")
    if not callback_url:
        decision = ask_human(question, **values, timeout_seconds=timeout_seconds, api_key=api_key, base_url=base_url)
        return parse_answer(decision.get("value"), review) if decision.get("status") == "answered" and decision.get("answered") else None

    created = CreatedDecision.model_validate(_kernel.create_durable_decision(question, **values, api_key=api_key, base_url=base_url))
    if created.status in ("expired", "cancelled"):
        return None
    from langgraph.types import interrupt

    correlation_id = created.correlation_id
    resumed = interrupt({
        "pushary": "decision",
        "decisionId": created.decision_id,
        "correlationId": correlation_id,
        "operationKey": values["idempotency_key"],
        "question": question,
        "type": review.type,
        "options": review.options,
        "external_id": external_id,
    })
    return parse_resume(resumed, correlation_id, review)
