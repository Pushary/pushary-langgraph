"""Offline Deep Agents review: real native interrupts, SQLite and fresh workers."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from typing import Literal

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, Interrupt
from pydantic import BaseModel, ConfigDict, Field
from pushary_langgraph import resolve_pushary_callback
from pushary_langgraph.review import ReviewRequest, parse_resume

CUSTOMER = "example-customer"
OPERATION = "example-order-revision-1"
THREAD: RunnableConfig = {"configurable": {"thread_id": "example-customer-thread"}}


class Order(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    quantity: int = Field(ge=1)


class NativeAction(BaseModel):
    model_config = ConfigDict(strict=True)
    name: Literal["submit_order"]
    args: Order


class NativeReview(BaseModel):
    model_config = ConfigDict(strict=True)
    action_requests: list[NativeAction] = Field(min_length=1, max_length=1)


class SavedReview(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    interrupt_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    request: ReviewRequest


class OfflineModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "offline-native-review"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs) -> OfflineModel:
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        response = AIMessage(content="Finished; no retry.") if any(isinstance(message, ToolMessage) for message in messages) else AIMessage(
            content="", tool_calls=[{"name": "submit_order", "args": {"quantity": 1}, "id": "example-call", "type": "tool_call"}],
        )
        return ChatResult(generations=[ChatGeneration(message=response)])


def build_agent(saver: SqliteSaver, directory: Path) -> CompiledStateGraph:
    @tool
    def submit_order(quantity: int) -> str:
        """Record the reviewed example order quantity."""
        with sqlite3.connect(directory / "business.sqlite") as database:
            database.execute("CREATE TABLE IF NOT EXISTS effects (operation TEXT PRIMARY KEY, quantity INTEGER)")
            database.execute("INSERT OR IGNORE INTO effects VALUES (?, ?)", (OPERATION, quantity))
        return "Example order recorded"

    return create_deep_agent(
        model=OfflineModel(), tools=[submit_order],
        interrupt_on={"submit_order": {"allowed_decisions": ["approve", "reject"]}},
        checkpointer=saver,
    )


def make_review(pending: Interrupt, customer: str, operation: str, callback_url: str = "https://example.invalid/review-callback") -> ReviewRequest:
    action = NativeReview.model_validate(pending.value).action_requests[0]
    return ReviewRequest(
        question=f"Approve {operation}: {action.args.quantity} item(s)?", external_id=customer,
        node=action.name, parameters=action.args.model_dump(),
        idempotency_key=f"{operation}:{pending.id}:0", callback_url=callback_url,
    )


def resume_review(agent: CompiledStateGraph, config: RunnableConfig, saved: SavedReview, payload: object, customer: str) -> Literal["resumed", "duplicate"]:
    if saved.request.external_id != customer:
        raise ValueError("Review belongs to another customer")
    pending = next((item for item in agent.get_state(config).interrupts if item.id == saved.interrupt_id), None)
    if pending is None:
        return "duplicate"
    action = NativeReview.model_validate(pending.value).action_requests[0]
    if action.name != saved.request.node or action.args.model_dump() != saved.request.parameters:
        raise ValueError("Pending action differs from the reviewed action")
    answer = parse_resume(payload, saved.correlation_id, saved.request)
    decision = {"type": "approve"} if answer == "yes" else {"type": "reject", "message": "This action was not approved. Do not retry it."}
    agent.invoke(Command(resume={pending.id: {"decisions": [decision]}}), config)
    return "resumed"


def simulated_callback(answer: str, correlation_id: str) -> object:
    body = json.dumps({"correlationId": correlation_id, "answer": answer, "answeredAt": "2026-10-02T00:00:00Z"})
    signature = hmac.new(b"example-webhook-secret", body.encode(), hashlib.sha256).hexdigest()
    verified = resolve_pushary_callback(body, signature, "example-webhook-secret")
    assert verified is not None
    assert resolve_pushary_callback(body, "invalid", "example-webhook-secret") is None
    return {"correlationId": verified["correlationId"], "answer": verified["answer"], "status": "answered"}


def run_phase(mode: str, directory: Path, outcome: str) -> None:
    with SqliteSaver.from_conn_string(str(directory / "checkpoint.sqlite")) as saver:
        agent = build_agent(saver, directory)
        path = directory / "review.json"
        if mode == "prepare":
            result = agent.invoke({"messages": [{"role": "user", "content": "Submit one item"}]}, THREAD)
            interrupts = result["__interrupt__"]
            assert len(interrupts) == 1
            request = make_review(interrupts[0], CUSTOMER, OPERATION)
            saved = SavedReview(interrupt_id=interrupts[0].id, correlation_id="simulated-decision", request=request)
            path.write_text(saved.model_dump_json())
            assert not (directory / "business.sqlite").exists()
            print("Saved native interrupt and simulated decision; action blocked")
            return
        saved = SavedReview.model_validate_json(path.read_text())
        payload = simulated_callback(outcome, saved.correlation_id) if outcome in ("yes", "no") else {
            "correlationId": saved.correlation_id, "answer": None, "status": outcome,
        }
        if mode == "invalid":
            changed = saved.model_copy(update={"request": saved.request.model_copy(update={"parameters": {"quantity": 2}})})
            invalid = [
                (saved, {"correlationId": "another-decision", "answer": "yes"}, CUSTOMER),
                (saved, {"correlationId": saved.correlation_id, "answer": "approve"}, CUSTOMER),
                (saved, {"correlationId": saved.correlation_id, "status": "expired", "answer": "yes"}, CUSTOMER),
                (saved, payload, "another-customer"), (changed, payload, CUSTOMER),
            ]
            for receipt, value, customer in invalid:
                try:
                    resume_review(agent, THREAD, receipt, value, customer)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid review resumed the action")
                assert agent.get_state(THREAD).interrupts
                assert not (directory / "business.sqlite").exists()
            return
        print(resume_review(agent, THREAD, saved, payload, CUSTOMER))


def refuse_network(*args, **kwargs) -> None:
    raise AssertionError("Offline example attempted a network connection")


def check() -> None:
    with tempfile.TemporaryDirectory(prefix="pushary-deepagents-") as root:
        for outcome in ("yes", "no", "expired", "cancelled"):
            directory = Path(root) / outcome
            directory.mkdir()
            for mode in ("prepare", "invalid", "resume", "resume"):
                result = subprocess.run([sys.executable, __file__, mode, str(directory), outcome], check=True, text=True, capture_output=True)
                if mode == "resume":
                    assert result.stdout.strip() in ("resumed", "duplicate")
            assert result.stdout.strip() == "duplicate"
            effects = 0
            if (directory / "business.sqlite").exists():
                with sqlite3.connect(directory / "business.sqlite") as database:
                    effects = database.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
            assert effects == (1 if outcome == "yes" else 0)
            print(f"{outcome}: restart, rejection and replay checks passed; effects={effects}")


if __name__ == "__main__":
    os.environ["LANGSMITH_TRACING"] = "false"
    if len(sys.argv) == 4:
        socket.socket.connect = refuse_network
        socket.socket.connect_ex = refuse_network
        run_phase(sys.argv[1], Path(sys.argv[2]), sys.argv[3])
    else:
        print("SIMULATION: real Deep Agents, SQLite and fresh workers; no phone, model API or external action.")
        check()
