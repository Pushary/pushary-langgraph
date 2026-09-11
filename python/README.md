# pushary-langgraph

[Connect your customer’s phone](https://pushary.com/sign-up?from=agent&plan=partner&utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=python-partner-start) · [Integration guide](https://pushary.com/docs/agents/adapters).

Native Pushary customer reviews for LangGraph: **confirm** for permission, **select**
for choices, **input** for missing details. Confirm supports lock-screen actions;
select/input open the app. The legacy web/PWA surface remains compatible.

## Install and enroll

```bash
pip install pushary-langgraph
```

```python
from pushary_langgraph import connect

invitation = connect(authenticated_customer.id)
```

Give the invitation to that authenticated customer. They install the native app,
reopen the link, and allow notifications. They need no Pushary account/key/paid plan;
the developer needs Partner access. Bind `external_id` in trusted application code,
not in model-generated tool arguments.

## Review a graph action

```python
from pushary_langgraph import pushary_interrupt


def review_order(state):
    answer = pushary_interrupt(
        f"Submit order {state['order_id']}, revision {state['revision']}?",
        external_id=state["customer_id"],
        idempotency_key=state["review_operation_id"],
        type="confirm",
        node="submit-order",
        parameters={"revision": state["revision"]},
        tool_target=state["order_id"],
        callback_url="https://your-app.example/pushary/callback",
    )
    return {"approved": answer == "yes"}
```

Your graph must route to the protected write only when this confirm branch approved.
`ask_human` is a blocking helper, not a rule forcing an agent to call it. A choice or
text answer is data, not action authorization; use `type="select", options=["A", "B"]`
or `type="input"` for the tool that needs those values. Do not use the shared SDK's
`approved` convenience flag as permission for a select/input action.

The adapter accepts the existing subject/presentation parameters: `tool_target`,
`actor`, `environment`, `parameters`, `presentation`, `placeholder`,
`expires_in_seconds` and `require_reachable`. A callback parks a native interrupt;
without it, the function blocks for the configured timeout and returns `None` unless
a valid answered result exists. Local timeout does not cancel the remote decision.

## Checkpoint and callback contract

Compile your graph with a persistent checkpointer and pass a stable, customer-scoped
`configurable.thread_id`. The whole node re-runs on resume; keep earlier work
idempotent. Same operation/recipient/request contents produce the same decision key;
changed contents produce a new key. Use an immutable reviewed business revision and
check that revision again before writing. Fingerprinting is not ownership validation.

The interrupt value includes `decisionId`, `correlationId`, `operationKey`, question,
type/options and recipient. Its enclosing LangGraph interrupt has a separate native
`id`. Your application must persist both IDs with its trusted thread/tenant mapping.

Verify callbacks with `resolve_pushary_callback(raw_body, signature, webhook_secret)`.
Persist verified callbacks before acknowledgement. Keep early answers queued until the
graph checkpoint and mapping exist. Your existing worker should serialize per thread,
reload the current checkpoint and match its exact pending interrupt. Completed
interrupts must not be resumed again on callback retries. After those checks:

```python
from langgraph.types import Command

graph.invoke(
    Command(resume={pending_interrupt.id: {
        "correlationId": verified_callback["correlationId"],
        "answer": verified_callback["answer"],
    }}),
    {"configurable": {"thread_id": trusted_thread_id}},
)
```

This is the final worker action, not an HTTP handler. The adapter validates the
correlation envelope and question-specific answer. It rejects strings/booleans passed
as an entire resume payload, wrong correlations, arbitrary answer objects, invalid
options and non-yes/no confirm values. A trusted expiration reconciler can send
`{"correlationId": decision_id, "status": "expired", "answer": None}` (or cancelled).
It returns `None`, never approval.

Handle missed callbacks by querying durable decision status; account for a crash
between graph resume and callback acknowledgement. Callback replay and checkpoint
persistence do not make ERP writes exactly once. Use operation keys and reconcile
uncertain external writes. No callback inbox or new orchestration runtime is installed
by this package.

## Upgrade and validation

Version 0.4 needs `pushary>=2.1`. Durable resumes now require the correlated object.
Finish already suspended 0.3 runs on their original adapter version; changing the
request fingerprint under a suspended checkpoint can invalidate its pending approval.

```bash
pip install -e '.[test]'
python -m unittest discover -s tests -v
```

[The restart test](tests/test_restart.py) uses the actual LangGraph graph and official
SQLite checkpointer, closes/reopens SQLite and rebuilds the graph for confirm yes/no,
select and input. HTTP is simulated; it does not deliver a phone notification or run
an ERP action. Tested with Python 3.12, LangGraph 1.2.11, SQLite checkpointer 3.1.1 and
Pydantic 2.13.5. These results do not certify every supported dependency version or
physical-device delivery.

[Official LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
describe persistence, replay and resuming by interrupt ID.

## License

MIT
