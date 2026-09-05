// Framework-free core for @pushary/langgraph. No LangChain imports live here, so it
// unit-tests without the framework installed. Everything below is the shared kernel
// from `@pushary/server/adapters`, bound to this adapter's name; the LangChain
// binding (the tool and the interrupt) lives in index.ts.

import {
  createAdapterKernel,
  type AskHumanInput,
  type PusharyAdapterConfig,
} from '@pushary/server/adapters'
import type { AskResult, DecisionType } from '@pushary/server'

export {
  SIGNATURE_HEADER,
  verifyWebhookSignature,
  parseDecisionCallback,
  deterministicKey,
  describeAnswer,
  isAffirmative,
  idempotencyKeyFor,
  resolvePusharyCallback,
} from '@pushary/server/adapters'

export type {
  AskHumanInput,
  CreatedDecision,
  PusharyCallback,
  PusharyAdapterConfig,
  ApprovalAsk,
  ApprovalDecision,
  ApprovalGate,
  PusharyGateConfig,
} from '@pushary/server/adapters'

export type { AskResult, DecisionType }

/** Config for every LangGraph helper in this package. */
export type PusharyLangGraphConfig = PusharyAdapterConfig

/** One ask, as a node or tool hands it to the helpers. */
export type PusharyAskInput = AskHumanInput

const kernel = createAdapterKernel('the LangGraph helpers')

/**
 * Blocking ask (Pattern A): create a decision and poll durably until the human
 * answers or the deadline passes. Each call creates a fresh decision unless the
 * caller supplies an idempotencyKey tied to its operation.
 */
export const askExternalUser = kernel.askExternalUser

/**
 * Durable create (Pattern B): open a decision with a callbackUrl and return at once.
 * Used by `pusharyInterrupt` right before it pauses the graph. Requires an explicit
 * idempotencyKey tied to the run and step so a resume reuses only that decision.
 */
export const createDurableDecision = kernel.createDurableDecision

/** Connect one end-user's phone (keyless). Show them the returned link. */
export const connect = kernel.connect
