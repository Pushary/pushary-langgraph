import { tool } from '@langchain/core/tools'
import { interrupt } from '@langchain/langgraph'
import { z } from 'zod'
import {
  askExternalUser,
  createDurableDecision,
  describeAnswer,
  type PusharyAskInput,
  type PusharyLangGraphConfig,
} from './core'

export * from './core'

export interface AskHumanToolOptions {
  /**
   * The enrolled end-user who answers. Bound here, NEVER taken from model input, so a
   * prompt-injected model cannot redirect an approval to another user.
   */
  readonly externalId: string
  /** Tool name the model calls (default "ask_human"). */
  readonly name?: string
  readonly description?: string
}

const ASK_INPUT_SCHEMA = z.object({
  question: z.string().describe('The exact question to put to the human.'),
  type: z
    .enum(['confirm', 'select', 'input'])
    .default('confirm')
    .describe('confirm = yes/no, select = pick an option, input = free text.'),
  options: z.array(z.string()).optional().describe('The choices, for a select question.'),
})

const DEFAULT_DESCRIPTION =
  'Ask a real human to approve, choose, or answer. Delivered to their phone and answered from the lock screen. Blocks until they reply. Use before any risky or irreversible action or when you need a human decision.'

/**
 * A LangChain tool that asks a real human and blocks until they answer, fail-closed.
 * Drop it into a prebuilt agent's tools, or call it from inside a node. The blocking
 * wait is bounded by `config.timeoutMs`; for waits longer than a request can hold,
 * use `pusharyInterrupt` instead.
 *
 * ```ts
 * const askHuman = createAskHumanTool({ apiKey: KEY }, { externalId: user.id })
 * const agent = createReactAgent({ llm, tools: [askHuman] })
 * ```
 */
export const createAskHumanTool = (config: PusharyLangGraphConfig, opts: AskHumanToolOptions) =>
  tool(
    async (input): Promise<string> => {
      const { question, type, options } = input
      const result = await askExternalUser(config, {
        question,
        type,
        options,
        externalId: opts.externalId,
        node: opts.name ?? 'ask_human',
      })
      return describeAnswer(type, result)
    },
    {
      name: opts.name ?? 'ask_human',
      description: opts.description ?? DEFAULT_DESCRIPTION,
      schema: ASK_INPUT_SCHEMA,
    },
  )

const coerceAnswer = (resumed: unknown): string | null => {
  if (typeof resumed === 'string') return resumed
  if (resumed && typeof resumed === 'object' && typeof (resumed as { answer?: unknown }).answer === 'string') {
    return (resumed as { answer: string }).answer
  }
  return resumed == null ? null : String(resumed)
}

/**
 * Ask a human from inside a LangGraph node, choosing the seam by whether you pass a
 * `callbackUrl`:
 *
 * - **No callbackUrl (Pattern A):** blocks and polls durably, returns the answer (or
 *   null if fail-closed). Zero extra infra, but holds the run open for the wait.
 * - **With callbackUrl (Pattern B):** opens the decision, then calls LangGraph's
 *   `interrupt()` to park the graph in your checkpointer. Pushary's signed webhook
 *   resumes the graph with `Command({ resume: answer })`. Survives worker death and
 *   holds no idle compute.
 *
 * The whole node re-runs on resume, so keep any code before this call idempotent. The
 * decision's idempotency key is derived from externalId + node + question, so the
 * re-run hits the same decision instead of paging the human twice.
 *
 * ```ts
 * async function approvalNode(state) {
 *   const answer = await pusharyInterrupt(
 *     { apiKey: KEY },
 *     { externalId: state.userId, question: 'Approve this transfer?', node: 'approval',
 *       callbackUrl: process.env.PUSHARY_CALLBACK_URL },
 *   )
 *   return { approved: answer === 'yes' }
 * }
 * ```
 */
export const pusharyInterrupt = async (
  config: PusharyLangGraphConfig,
  input: PusharyAskInput,
): Promise<string | null> => {
  if (!input.callbackUrl) {
    const result = await askExternalUser(config, input)
    return result.answered ? result.value : null
  }
  // Open the durable decision first, then park the graph. On the first pass
  // interrupt() throws a GraphInterrupt that must propagate to the runtime; on resume
  // the node re-runs, createDurableDecision replays onto the same decision (stable
  // idempotency key), and interrupt() returns the resume value.
  await createDurableDecision(config, input)
  const resumed = interrupt({
    pushary: 'decision',
    question: input.question,
    externalId: input.externalId,
  })
  return coerceAnswer(resumed)
}
