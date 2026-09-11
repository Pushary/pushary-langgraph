import { tool } from '@langchain/core/tools'
import { interrupt } from '@langchain/langgraph'
import { questionSchema, prepareReview, parseReviewAnswer, parseReviewResume, createdDecisionSchema } from './review'
export type { PusharyInterruptResume } from './review'
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

const DEFAULT_DESCRIPTION =
  'Ask a customer to approve, choose, or answer in the native Pushary app. Confirm requests support lock-screen actions; select and input open the app. This optional tool does not enforce approval of other tools.'

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
      schema: questionSchema,
    },
  )

export const pusharyInterrupt = async (
  config: PusharyLangGraphConfig,
  input: PusharyAskInput,
): Promise<string | null> => {
  const reviewed = prepareReview(input)
  if (!reviewed.callbackUrl) {
    const result = await askExternalUser(config, reviewed)
    return result.status === 'answered' && result.answered ? parseReviewAnswer(result.value, reviewed) : null
  }
  const created = createdDecisionSchema.parse(await createDurableDecision(config, reviewed))
  if (created.status === 'expired' || created.status === 'cancelled') return null
  const resumed = interrupt({
    pushary: 'decision',
    decisionId: created.decisionId,
    correlationId: created.correlationId,
    operationKey: reviewed.idempotencyKey,
    question: reviewed.question,
    type: reviewed.type,
    options: reviewed.options,
    externalId: reviewed.externalId,
  })
  return parseReviewResume(resumed, created.correlationId, reviewed)
}
