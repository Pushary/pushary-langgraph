// Run after npm install && npm run build. No model API key.
import { StateGraph, Annotation, START, END } from '@langchain/langgraph'
import { askExternalUser, connect as enroll } from '../dist/index.js'
import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { createInterface } from 'node:readline/promises'

const live = process.argv.includes('--live')
if (process.argv.slice(2).some(arg => arg !== '--live')) throw new Error('Usage: node examples/refund.mjs [--live]')
const config = live
  ? { apiKey: process.env.PUSHARY_API_KEY, timeoutMs: 55000 }
  : { apiKey: 'pk_demo.sk_demo', baseUrl: 'https://simulation.invalid', timeoutMs: 0 }
const externalId = live ? process.env.PUSHARY_EXTERNAL_ID : 'demo-user'
if (live && (!config.apiKey || !externalId)) {
  throw new Error('Live mode needs PUSHARY_API_KEY and PUSHARY_EXTERNAL_ID. Use your own test user.')
}
if (live) {
  const { universalLink } = await enroll(config, externalId)
  const terminal = createInterface({ input: process.stdin, output: process.stdout })
  try {
    console.log('Connect your test phone:', universalLink)
    await terminal.question('Open the link and finish connecting before pressing Enter. ')
  } finally { terminal.close() }
}
console.log(live
  ? 'LIVE PHONE: real approval; simulated refund. No money moves.'
  : 'SIMULATION: real framework and adapter; fake API answers. No network, phone, or money movement.')

const realFetch = globalThis.fetch
try {
  for (const answer of live ? ['phone'] : ['yes', 'no', 'unanswered']) {
    let decisionRequests = 0
    if (!live) globalThis.fetch = async (input) => {
      const url = new URL(String(input))
      assert.equal(url.origin, 'https://simulation.invalid', 'Unexpected network request')
      if (url.pathname === '/authorize') return Response.json({
        verdict: 'requires_human', policy: null, authorizationId: null, reason: 'Demo requires a person.',
      })
      assert.equal(url.pathname, '/decisions', 'Unexpected API endpoint')
      decisionRequests++
      return Response.json({
        decisionId: 'demo-decision', type: 'confirm',
        status: answer === 'unanswered' ? 'pending' : 'answered',
        answered: answer !== 'unanswered', value: answer === 'unanswered' ? null : answer,
      })
    }
    let executions = 0

    const State = Annotation.Root({ approved: Annotation() })
    const graph = new StateGraph(State)
      .addNode('approval', async () => {
        const decision = await askExternalUser(config, {
          externalId, question: 'Approve a simulated $40 refund for DEMO-123?',
          type: 'confirm', node: 'refund-approval', idempotencyKey: randomUUID(),
        })
        return { approved: decision.approved === true }
      })
      .addNode('refund', async () => { executions++; return {} })
      .addEdge(START, 'approval')
      .addConditionalEdges('approval', state => state.approved ? 'refund' : END)
      .addEdge('refund', END)
      .compile()
    await graph.invoke({ approved: false })

    if (!live) {
      assert.equal(decisionRequests, 1, 'The example must actually request a decision')
      assert.equal(executions, answer === 'yes' ? 1 : 0, 'Only explicit approval may execute')
    }
    console.log(`${answer}: ${executions ? 'executed' : 'blocked'} (simulated refund)`)
  }
} finally { globalThis.fetch = realFetch }
console.log('Found this useful? Star this repo, or share a reproducible issue and help improve it.')

