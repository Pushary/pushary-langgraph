# pushary-langgraph

Human-in-the-loop for [LangGraph](https://langchain-ai.github.io/langgraph/) and
LangChain. Ask a real human to approve, and get the answer on their phone. Two seams:

- **A blocking `ask_human`** you call from inside a node.
- **A durable `pushary_interrupt`** that parks the graph with LangGraph's native
  `interrupt()` and resumes on a signed webhook, so a long wait holds no compute and
  survives a restart.

Requires the Pushary [Partner plan](https://pushary.com/agent-notifications-integration).

## Install

```bash
pip install pushary-langgraph
```

Set `PUSHARY_API_KEY` (get it in your [dashboard](https://pushary.com/dashboard/settings)).

## Connect a phone once

```python
from pushary_langgraph import connect

link = connect("user_123")  # show this to your end-user; one tap connects their phone
```

## Ask a human inside a node

```python
from pushary_langgraph import ask_human

def approval_node(state):
    d = ask_human("Approve this transfer?", external_id=state["user_id"], node="approval")
    return {"approved": d["approved"]}
```

`ask_human` blocks, polls durably, and fails closed. The idempotency key is derived
from `external_id + node + question`, so a node that re-runs on resume hits the same
decision instead of paging the human twice.

## Durable interrupt

```python
from pushary_langgraph import pushary_interrupt

def approval_node(state):
    answer = pushary_interrupt(
        "Approve this transfer?",
        external_id=state["user_id"],
        node="approval",
        callback_url=os.environ["PUSHARY_CALLBACK_URL"],  # omit to block instead of park
    )
    return {"approved": answer == "yes"}
```

With a `callback_url`, the node opens the decision and calls LangGraph's `interrupt()`
to park the graph (a checkpointer is required). Keep any code before the call
idempotent, the whole node re-runs on resume.

### Resume from the webhook

```python
from pushary_langgraph import resolve_pushary_callback, SIGNATURE_HEADER
from langgraph.types import Command

# POST /pushary/callback
def callback(request):
    raw = request.body
    cb = resolve_pushary_callback(raw, request.headers.get(SIGNATURE_HEADER), os.environ["PUSHARY_WEBHOOK_SECRET"])
    if not cb:
        return ("bad signature", 401)
    thread_id = lookup_thread(cb["correlationId"])  # your own correlationId -> thread_id map
    graph.invoke(Command(resume=cb["answer"]), {"configurable": {"thread_id": thread_id}})
    return ("ok", 200)
```

## API

- `connect(external_id, *, api_key=None, base_url=None)` — enroll an end-user's phone, returns the link.
- `ask_human(question, *, external_id, type="confirm", options=None, node=..., ...)` — blocking, returns the decision dict.
- `pushary_interrupt(question, *, external_id, node=..., callback_url=None, ...)` — blocking, or durable when `callback_url` is set.
- `resolve_pushary_callback(raw_body, signature, secret)` — verify + parse a callback into `{correlationId, answer, approved, ...}`.
- `describe_answer(type, result)`, `is_affirmative(answer)`, `deterministic_key(parts)`, `SIGNATURE_HEADER`.

## License

MIT
