# LangGraph: approval before a refund

Run from a clone of this public repository with Node.js 22:

```bash
npm install
npm run build
node examples/refund.mjs
```

The example uses the real framework and Pushary adapter. In local mode it intercepts
fetch with fixed API responses and never reaches the network. The graph is deterministic and needs no language model.
The refund only increments a local counter. No payment service is connected.
Assertions verify that yes executes once, while no and unanswered execute zero times.
The approval node controls a conditional edge; an LLM instruction is not the enforcement boundary.

## Try real phone delivery

You need a Pushary API key with Partner access and your own test user. Keep the key
in your shell environment; do not commit it or paste it into an issue.

1. Set `PUSHARY_API_KEY` and `PUSHARY_EXTERNAL_ID` in your shell.
2. Run `node examples/refund.mjs --live`.
3. Open the returned enrollment link on your phone and finish connecting.
4. Press Enter in the terminal. An approval is sent to that test user.
5. Answer on the phone. The terminal shows whether the simulated refund executed.

Live mode makes real API calls and can consume your plan's usage. The refund
remains simulated. The human-answer wait is bounded to 55 seconds and no answer blocks execution. Enrollment has separate timeouts.
A successful local run does not prove device reachability, authentication, or push delivery.

For a production integration, keep the enrolled identity bound in trusted server
code, persist an operation id across retries, and make the actual refund idempotent.
For long waits, use the durable workflow path in the main README.

## A useful bug report

Include Node, framework, and adapter versions; the command you ran; expected and
actual output; and your OS. Redact API keys, enrollment links, user data, and session ids.
Open a public issue or PR using [the contribution guide](../CONTRIBUTING.md).
