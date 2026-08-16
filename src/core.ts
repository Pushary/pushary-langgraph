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
 * answers or the deadline passes. The idempotency key is derived from
 * externalId + node + question, so a LangGraph node that re-runs on resume hits the
 * same decision instead of paging twice.
 */
export const askExternalUser = kernel.askExternalUser

/**
 * Durable create (Pattern B): open a decision with a callbackUrl and return at once.
 * Used by `pusharyInterrupt` right before it pauses the graph. Same deterministic
 * idempotency key as the blocking path, so the node's re-run on resume is safe.
 */
export const createDurableDecision = kernel.createDurableDecision

/** Connect one end-user's phone (keyless). Show them the returned link. */
export const connect = kernel.connect
