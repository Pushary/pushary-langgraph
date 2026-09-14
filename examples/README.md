# Pause an order workflow, get customer approval on a phone, then resume

A customer requests a $40 refund for order DEMO-123. Before the workflow reaches
its refund step, it asks that customer to approve. Only an explicit yes opens the
edge to the refund node. A rejection or no answer ends the run without executing it.

This tutorial uses [the complete runnable example](refund.mjs), the real LangGraph
runtime, and `@pushary/langgraph`. The refund is a local counter so you can explore
the approval flow without connecting a payment processor.

## 1. Run the three outcomes locally

Use Node.js 22 or newer:


```bash
git clone https://github.com/Pushary/pushary-langgraph.git
cd pushary-langgraph
npm install
npm run build
node examples/refund.mjs
```

The example uses the real framework and Pushary adapter. In local mode it intercepts
fetch with fixed API responses and never reaches the network. The graph is deterministic and needs no language model.
The refund only increments a local counter. No payment service is connected.
Assertions verify that yes executes once, while no and unanswered execute zero times.
The approval node controls a conditional edge; an LLM instruction is not the enforcement boundary.

A checked run produces:

```text
yes: executed (simulated refund)
no: blocked (simulated refund)
unanswered: blocked (simulated refund)
```

## 2. Understand the enforcement

The graph is `START → approval → refund → END` for yes, and
`START → approval → END` otherwise. The approval node awaits the customer's
answer and returns a boolean. The conditional edge enforces it:

```js
const decision = await askExternalUser(config, {
  externalId, question: 'Approve a simulated $40 refund for DEMO-123?',
  type: 'confirm', node: 'refund-approval', idempotencyKey: randomUUID(),
})
return { approved: decision.approved === true }
```

```js
.addConditionalEdges('approval', state => state.approved ? 'refund' : END)
```

These fragments come from [refund.mjs](refund.mjs); run that file for the complete
graph. It creates a new operation key for each demonstration. In an application,
reuse a persisted key for retries of the same reviewed action.

## 3. Get a real answer from a phone

You need a Pushary API key with Partner access and your own test user. Keep the key
in your shell environment; do not commit it or paste it into an issue.

1. Set `PUSHARY_API_KEY` and `PUSHARY_EXTERNAL_ID` in your shell.
2. Run `node examples/refund.mjs --live`.
3. Open the returned enrollment link on your test phone and finish connecting. The customer needs the Pushary app and notification permission; after installing, reopen the link. An already enrolled test phone can be reused.
4. Press Enter in the terminal. An approval is sent to that test user.
5. Answer on the phone. Confirm notifications support yes/no lock-screen actions; choices and text answers open the app. The terminal prints `phone: executed (simulated refund)` for yes or `phone: blocked (simulated refund)` otherwise.

The developer needs [Partner access](https://pushary.com/sign-up?from=agent&plan=partner&utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=tutorial). The enrolled customer does not need a Pushary account or API key.
Never publish the enrollment link: it is intended for that customer.

Live mode makes real API calls and can consume your plan's usage. The refund
remains simulated. The human-answer wait is bounded to 55 seconds and no answer blocks execution. Enrollment has separate timeouts.
A successful local run does not prove device reachability, authentication, or push delivery.

### Recorded demonstration (2026-09-14)

The public example was built and run with `@pushary/langgraph@0.4.0`.
The local three-outcome demonstration above passed, along with all 13 adapter
tests and TypeScript checks. A separate live run used a temporary Partner test
key bound to an existing enrolled customer:

```text
LIVE PHONE: real approval; simulated refund. No money moves.
phone: blocked (simulated refund)
```

The real decision API returned HTTP 200. No human answer was recorded within the
55-second wait, so the protected node did not run. The pending decision was then
cancelled and the temporary key revoked. This demonstrates the live unanswered
path; it does not establish that a notification reached the device or that a
phone approval successfully resumed the graph. Run the steps above and answer
yes to verify that path with your own test phone.

## 4. Let a customer answer after the worker exits

This demonstration keeps the worker alive for a bounded wait. It does not save a
checkpoint or restart the process while waiting. For that behavior, use the
[durable native interrupt and callback contract](../README.md#durable-native-interrupt)
with a persistent checkpointer and a verified, correlated callback. The adapter's
[restart tests](../src/interrupt.test.ts) close and reopen SQLite before resuming;
their HTTP responses are simulated.

For a production integration, keep the enrolled identity bound in trusted server
code, persist an operation id across retries, and make the actual refund idempotent.
For long waits, use the durable workflow path in the main README.

## A useful bug report

Include Node, framework, and adapter versions; the command you ran; expected and
actual output; and your OS. Redact API keys, enrollment links, user data, and session ids.
Open a public issue or PR using [the contribution guide](../CONTRIBUTING.md).
