# @pushary/langgraph

Your graph pauses; your customer answers on their phone. Resume the saved review with yes/no, a choice or text.

[Integration guide](https://pushary.com/human-in-the-loop-langgraph?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=guide) · [Connect your customer’s phone](https://pushary.com/sign-up?from=agent&plan=partner&utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=partner-start) · [Report a problem](https://github.com/Pushary/pushary-langgraph/issues)

Listed in the [LangChain JavaScript tools directory](https://docs.langchain.com/oss/javascript/integrations/tools/index) and [provider directory](https://docs.langchain.com/oss/javascript/integrations/providers/all_providers).

**Tutorial: [Pause an order workflow, get customer approval on a phone, then resume](examples/README.md).**
Use the runnable refund example to gate a $40 refund for order DEMO-123.

## Try it before signing up

[Open the no-signup browser demo](https://pushary.com/try?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=demo).
It demonstrates a human approval with an open phone page and temporary state;
it does **not** demonstrate push delivery or durable production storage.

For a local example using the real LangGraph conditional routing:

```bash
git clone https://github.com/Pushary/pushary-langgraph.git
cd pushary-langgraph
npm install
npm run build
node examples/refund.mjs
```

Use Node.js 22. No account, card, API key, or model provider is needed for this simulation.
It checks all three outcomes:

```text
yes: executed (simulated refund)
no: blocked (simulated refund)
unanswered: blocked (simulated refund)
```

[Read the example and try a real phone approval](examples/README.md).
The integration code is MIT-licensed; real phone delivery uses the hosted Pushary service and requires Partner access.

[Get help or contribute an example](CONTRIBUTING.md).

[![CI](https://github.com/Pushary/pushary-langgraph/actions/workflows/ci.yml/badge.svg)](https://github.com/Pushary/pushary-langgraph/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@pushary/langgraph)](https://www.npmjs.com/package/@pushary/langgraph)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Human-in-the-loop for LangGraph and LangChain using the native Pushary app. Reuse
**confirm** for permission, **select** for a choice and **input** for missing details.
Confirm notifications have lock-screen actions; choices and free text open the app.
The older browser/PWA decision surface remains a compatibility path.

## Install and connect

```bash
npm i @pushary/langgraph @langchain/langgraph @langchain/core zod
```

```ts
import { connect } from '@pushary/langgraph'

const { universalLink } = await connect({ apiKey: process.env.PUSHARY_API_KEY }, authenticatedCustomer.id)
```

Deliver this link to that authenticated customer. Native enrollment requires the app
and notification permission; after installation reopen the invitation. The customer
needs no Pushary account, key or paid plan; the developer needs Partner access.
`externalId` must come from trusted application ownership, never model-generated input.

## Optional ask tool vs enforced graph review

`createAskHumanTool(config, { externalId })` offers a model a blocking question tool.
It does not enforce approval before other tools. Enforce review through graph topology:
put the interrupt before the protected action and route to that action only when the
**confirm** result equals `'yes'`. A select/input answer is data, even when its text
happens to be `'yes'`; it is not authorization to run another tool.

The blocking path has a bounded local wait. `pusharyInterrupt` returns `null` when
unanswered, expired or cancelled; timeout does not cancel the remote decision. Use
the interrupt path for a customer who might answer after the worker exits.

## Durable native interrupt

```ts
import { pusharyInterrupt } from '@pushary/langgraph'

async function reviewOrder(state: OrderState) {
  const answer = await pusharyInterrupt(
    { apiKey: process.env.PUSHARY_API_KEY },
    {
      externalId: state.customerId,
      idempotencyKey: state.reviewOperationId,
      node: 'submit-order',
      question: `Submit order ${state.orderId}, revision ${state.revision}?`,
      type: 'confirm',
      toolTarget: state.orderId,
      parameters: { revision: state.revision, amount: state.amountMinor },
      presentation: {
        label: 'Submit sales order',
        effect: 'Creates this reviewed revision in your ERP.',
        changes: [{ parameter: 'amount', label: 'Total', format: { kind: 'currency', currency: 'EUR' } }],
      },
      callbackUrl: process.env.PUSHARY_CALLBACK_URL,
    },
  )
  return { approved: answer === 'yes' }
}
```

`OrderState` above is your validated business state. Store an immutable revision and
check it again at the protected write. Define graph edges so rejection/null cannot
reach that write. For a choice use `type:'select', options:['A','B']`; for text use
`type:'input'`. Presentation and subject fields use the existing server SDK contract.

Compile with a persistent LangGraph checkpointer and supply a stable, customer-scoped
`configurable.thread_id`. `MemorySaver` is not restart durability. The whole node
executes again on resume, so code before the interrupt must be idempotent. The adapter
fingerprints the supplied operation key, recipient and request contents; same request
retries reuse a decision, while changed recipients/arguments/presentation get a new
identity. Keep the request stable across replay and use a fresh operation key for a
new action. Fingerprinting does not verify ownership or make an ERP write idempotent.

The interrupt payload contains `decisionId`, `correlationId`, `operationKey`, `type`,
`question`, `options` and `externalId`. The native LangGraph interrupt also has its
own `id`; keep both IDs. The SDK's created decision is not thrown away.

## Callback integration contract

The adapter does not install an HTTP route or callback inbox. Your application must:

1. Verify the raw request using `resolvePusharyCallback(raw, signature, webhookSecret)`
   and persist the verified callback before acknowledging it. Select the secret and
   tenant from trusted endpoint configuration, not callback text.
2. Persist the association between tenant/customer, operation, thread ID, interrupt
   ID and Pushary correlation ID after the checkpoint is ready. An early callback
   stays queued until this association exists; do not discard it as an unknown ID.
3. Serialize processing per thread using your existing job/transaction mechanism,
   reload its current checkpoint, and match the exact pending interrupt. If a retry
   finds that interrupt already completed, acknowledge it without resuming another.
4. Resume by native interrupt ID with the **correlated object**:

```ts
import { Command } from '@langchain/langgraph'

await graph.invoke(new Command({
  resume: {
    [pendingInterrupt.id]: {
      correlationId: verifiedCallback.correlationId,
      answer: verifiedCallback.answer,
    },
  },
}), { configurable: { thread_id: trustedThreadId } })
```

This is a worker fragment after the checks above, not a complete webhook handler.
Resume data is schema-validated: wrong correlation, arbitrary objects, invalid select
options and non-yes/no confirm answers throw instead of permitting execution. A trusted
expiry/cancellation reconciler may resume `{ correlationId, status:'expired', answer:null }`
(or `'cancelled'`); never fabricate an approval to release a waiting graph. Don't use
`verifiedCallback.approved` to authorize a select/input operation.

Persist processing outcomes, reconcile remote decision status if a webhook is missed,
and handle a crash between graph resume and callback acknowledgement. Notifications
and callbacks may repeat. Review/checkpoint persistence does not guarantee exactly-once
external effects; use the ERP's operation key and reconcile uncertain writes.

## Upgrade from 0.3

0.4 requires server SDK 2.1 and rejects bare string/boolean durable resumes. Send the
correlation envelope above. Existing suspended 0.3 runs must finish under their old
adapter version; do not change adapter code/fingerprints underneath parked checkpoints.
The function still returns `string | null` and validates that string for its question
type. Keep `answer === 'yes'` only on a confirm permission branch.

## Run the persistence checks

```bash
npm install
npm test
npm run typecheck
npm run build
```

[The restart test](src/interrupt.test.ts) uses real LangGraph and its official SQLite
checkpointer, closes/reopens the database and rebuilds the graph before resuming.
HTTP is simulated; no model, phone notification, callback server or ERP is contacted.
It also checks action identity and rejected resume payloads. Tested here with
LangGraph JS 1.4.10 and SQLite checkpointer 1.0.4; the wider peer range is not a claim
that every version was exercised. SQLite is a development dependency, not a new
Pushary runtime. The application chooses its production checkpointer.

[LangGraph interrupt semantics](https://docs.langchain.com/oss/javascript/langgraph/interrupts)
cover node replay, persistence and interrupt-ID addressing.

## Python

The matching package is `pushary-langgraph`; see [python/README.md](python/README.md)
in the published repository. Both languages use native interrupts and the existing
Pushary decision service. Neither the optional ask tool nor an LLM instruction is an
enforced action gate.

## License

[MIT](LICENSE) © Pushary
