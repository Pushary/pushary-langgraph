import { afterEach, describe, expect, it } from 'vitest'
import { Annotation, Command, END, START, StateGraph } from '@langchain/langgraph'
import { SqliteSaver } from '@langchain/langgraph-checkpoint-sqlite'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pusharyInterrupt } from './index'
import { parseReviewResume, prepareReview } from './review'
const config = { apiKey: 'pk_test.sk_test', baseUrl: 'https://test.invalid', timeoutMs: 0 }
const input = { externalId: 'customer', question: 'Approve order revision 1?', idempotencyKey: 'order-1', callbackUrl: 'https://test.invalid/callback', parameters: { revision: 1 } }
const originalFetch = globalThis.fetch
const State = Annotation.Root({ answer: Annotation<string | null>() })
const graphFor = (saver: SqliteSaver, type: 'confirm' | 'select' | 'input' = 'confirm') => new StateGraph(State)
  .addNode('review', async () => ({ answer: await pusharyInterrupt(config, { ...input, type, options: type === 'select' ? ['A', 'B'] : undefined }) }))
  .addEdge(START, 'review').addEdge('review', END).compile({ checkpointer: saver })
afterEach(() => { globalThis.fetch = originalFetch })
describe('correlated LangGraph review', () => {
  it('reopens SQLite checkpoints for each response type without creating another decision', async () => {
    const directory = mkdtempSync(join(tmpdir(), 'pushary-langgraph-'))
    try {
      for (const [type, answer] of [['confirm', 'yes'], ['confirm', 'no'], ['select', 'B'], ['input', 'Dock 2']] as const) {
        const keys = new Set<string>()
        globalThis.fetch = (async (_url, init) => {
          const body = JSON.parse(String(init?.body)); keys.add(body.idempotencyKey)
          return Response.json({ decisionId: body.idempotencyKey, status: 'pending' })
        }) as typeof fetch
        const path = join(directory, `${type}-${answer}.sqlite`)
        const firstSaver = SqliteSaver.fromConnString(path)
        const graph = graphFor(firstSaver, type)
        const thread = { configurable: { thread_id: type } }
        await graph.invoke({}, thread)
        const pending = (await graph.getState(thread)).tasks.flatMap((task) => task.interrupts)[0]
        expect(pending?.id).toBeTruthy()
        const payload = pending!.value as { correlationId: string; decisionId: string; type: string }
        expect(payload.correlationId).toBe(payload.decisionId); expect(payload.type).toBe(type)
        firstSaver.db.close()
        const resumedSaver = SqliteSaver.fromConnString(path)
        try {
          const resumedGraph = graphFor(resumedSaver, type)
          const result = await resumedGraph.invoke(new Command({ resume: { [pending!.id!]: { correlationId: payload.correlationId, answer } } }), thread)
          expect(result.answer).toBe(answer); expect(keys.size).toBe(1)
          expect((await resumedGraph.getState(thread)).next).toEqual([])
        } finally { resumedSaver.db.close() }
      }
    } finally { rmSync(directory, { recursive: true, force: true }) }
  })
  it('returns no approval when replay finds an expired or cancelled decision', async () => {
    for (const status of ['expired', 'cancelled']) {
      globalThis.fetch = (async () => Response.json({ decisionId: 'decision-1', status })) as typeof fetch
      expect(await pusharyInterrupt(config, input)).toBeNull()
    }
  })
  it('preserves opaque recipient and operation identities before sending', async () => {
    const sent: Array<{ externalId: string; idempotencyKey: string }> = []
    globalThis.fetch = (async (_url, init) => {
      sent.push(JSON.parse(String(init?.body)))
      return Response.json({ decisionId: 'decision-1', status: 'expired' })
    }) as typeof fetch
    for (const idempotencyKey of [' operation ', 'operation']) {
      await pusharyInterrupt(config, { ...input, externalId: ' customer ', idempotencyKey })
    }
    expect(sent.map((body) => body.externalId)).toEqual([' customer ', ' customer '])
    expect(sent[0].idempotencyKey).not.toBe(sent[1].idempotencyKey)
    await pusharyInterrupt(config, { ...input, externalId: '😀'.repeat(128) })
    expect(sent).toHaveLength(3)
    for (const externalId of [' ', 'a'.repeat(257), '😀'.repeat(129)]) {
      await expect(pusharyInterrupt(config, { ...input, externalId })).rejects.toThrow()
    }
    await expect(pusharyInterrupt(config, { ...input, callbackUrl: undefined, idempotencyKey: ' ' })).rejects.toThrow()
    expect(sent).toHaveLength(3)
  })
  it('binds retry identity to recipient and exact action', () => {
    const original = prepareReview(input).idempotencyKey
    expect(prepareReview({ ...input }).idempotencyKey).toBe(original)
    expect(prepareReview({ ...input, externalId: 'other' }).idempotencyKey).not.toBe(original)
    expect(prepareReview({ ...input, parameters: { revision: 2 } }).idempotencyKey).not.toBe(original)
    expect(prepareReview({ ...input, parameters: { a: 1, b: 2 } }).idempotencyKey).toBe(prepareReview({ ...input, parameters: { b: 2, a: 1 } }).idempotencyKey)
    expect(() => prepareReview({ ...input, idempotencyKey: undefined })).toThrow()
  })
  it('rejects uncorrelated or wrong-type answers and treats expiry as no approval', () => {
    for (const value of ['yes', true, {}, { correlationId: 'wrong', answer: 'yes' }, { correlationId: 'd', answer: { approved: true } }, { correlationId: 'd', answer: 'anything' }]) expect(() => parseReviewResume(value, 'd', input)).toThrow()
    expect(parseReviewResume({ correlationId: 'd', answer: null, status: 'expired' }, 'd', input)).toBeNull()
    expect(() => parseReviewResume({ correlationId: 'd', answer: 'yes', status: 'expired' }, 'd', input)).toThrow()
    expect(() => parseReviewResume({ correlationId: 'd', answer: 'C' }, 'd', { ...input, type: 'select', options: ['A', 'B'] })).toThrow()
  })
})
