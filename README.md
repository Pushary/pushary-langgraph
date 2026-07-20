# @pushary/langgraph

[![CI](https://github.com/Pushary/pushary-langgraph/actions/workflows/ci.yml/badge.svg)](https://github.com/Pushary/pushary-langgraph/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@pushary/langgraph)](https://www.npmjs.com/package/@pushary/langgraph)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Human-in-the-loop for [LangGraph](https://langchain-ai.github.io/langgraphjs/) and
LangChain. Ask a real human to approve, and get the answer on their phone. Two seams:

- **A blocking `ask_human` tool** for a straightforward approval inside a request.
- **A durable `interrupt()` wrapper** that parks the graph in your checkpointer and
  resumes on a signed webhook, so an hour-long wait holds no compute and survives a
  restart.

Full walkthrough: [Human-in-the-loop for LangGraph](https://pushary.com/human-in-the-loop-langgraph?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=readme).
Reaching your own end-users on their phones is the Pushary
[Partner plan](https://pushary.com/human-in-the-loop?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=readme).

## Install

```bash
npm i @pushary/langgraph @langchain/langgraph @langchain/core
```

Set `PUSHARY_API_KEY` (get it in your [dashboard](https://pushary.com/dashboard/settings)).

## Connect a phone once

```ts
import { connect } from '@pushary/langgraph'

const { universalLink } = await connect({ apiKey: process.env.PUSHARY_API_KEY! }, user.id)
// show universalLink to the user; one tap connects their phone
```

## Blocking tool

```ts
import { createAskHumanTool } from '@pushary/langgraph'
import { createReactAgent } from '@langchain/langgraph/prebuilt'

const askHuman = createAskHumanTool({ apiKey: process.env.PUSHARY_API_KEY! }, { externalId: user.id })
const agent = createReactAgent({ llm, tools: [askHuman] })
```

The tool blocks until the person answers and returns a fail-closed instruction to the
model ("The human declined. Do not proceed."). `externalId` is bound in code, never
taken from model input, so a prompt-injected model cannot ask the wrong person.

## Durable interrupt

Wrap LangGraph's native `interrupt()`. Pass a `callbackUrl` to park the graph instead
of blocking.

```ts
import { pusharyInterrupt } from '@pushary/langgraph'
import { StateGraph, MemorySaver, Command } from '@langchain/langgraph'

async function approvalNode(state) {
  const answer = await pusharyInterrupt(
    { apiKey: process.env.PUSHARY_API_KEY! },
    {
      externalId: state.userId,
      question: 'Approve this transfer?',
      node: 'approval',
      callbackUrl: process.env.PUSHARY_CALLBACK_URL, // omit to block instead of park
    },
  )
  return { approved: answer === 'yes' }
}

const graph = builder.compile({ checkpointer: new MemorySaver() }) // a checkpointer is required
```

The whole node re-runs on resume, so keep any code before `pusharyInterrupt`
idempotent. The decision's idempotency key is derived from `externalId + node +
question`, so the re-run lands on the same decision instead of paging the human twice.

### Resume from the webhook

```ts
import { resolvePusharyCallback } from '@pushary/langgraph'
import { Command } from '@langchain/langgraph'

// POST /pushary/callback
export async function POST(req: Request) {
  const raw = await req.text()
  const cb = resolvePusharyCallback(raw, req.headers.get('x-pushary-signature'), process.env.PUSHARY_WEBHOOK_SECRET!)
  if (!cb) return new Response('bad signature', { status: 401 })
  const threadId = await lookupThread(cb.correlationId) // your own correlationId -> thread_id map
  await graph.invoke(new Command({ resume: cb.answer }), { configurable: { thread_id: threadId } })
  return new Response('ok')
}
```

## API

- `connect(config, externalId)` — enroll an end-user's phone.
- `createAskHumanTool(config, { externalId })` — a LangChain `tool()` that blocks on a human.
- `pusharyInterrupt(config, input)` — ask from a node: blocking, or durable when `callbackUrl` is set.
- `resolvePusharyCallback(raw, signature, secret)` — verify + parse a callback into `{ correlationId, answer, approved, ... }`.
- `askExternalUser`, `createDurableDecision`, `describeAnswer`, `isAffirmative`, `deterministicKey`, `SIGNATURE_HEADER`.

## Python

The same two seams ship for Python (LangGraph's Python `interrupt()` plus a blocking
`ask_human`). The package lives in [`python/`](python) and on PyPI:

```bash
pip install pushary-langgraph
```

See [python/README.md](python/README.md) for the Python API.

## Other frameworks

The same two calls work in [CrewAI](https://pushary.com/human-in-the-loop-crewai?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=readme),
the [Vercel AI SDK](https://pushary.com/human-in-the-loop-vercel-ai-sdk?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=readme),
[Mastra](https://pushary.com/human-in-the-loop-mastra?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=readme),
the [OpenAI Agents SDK](https://pushary.com/human-in-the-loop-openai-agents-sdk?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=readme), and
[more](https://pushary.com/human-in-the-loop?utm_source=github&utm_medium=oss-adapter&utm_campaign=pushary-langgraph&utm_content=readme).

## Example

A runnable example is in [`examples/`](examples).

## License

[MIT](LICENSE) © Pushary
