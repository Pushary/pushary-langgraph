import { z } from 'zod'
import { decisionFingerprint } from '@pushary/server/adapters'
import type { PusharyAskInput } from './core'

export const questionSchema = z.object({
  question: z.string().trim().min(1),
  type: z.enum(['confirm', 'select', 'input']).default('confirm'),
  options: z.array(z.string().min(1)).optional(),
})

const reviewSchema = questionSchema.extend({
  externalId: z.string().max(256).refine((value) => value.trim().length > 0),
  idempotencyKey: z.string().refine((value) => value.trim().length > 0).optional(),
})

export const createdDecisionSchema = z.object({
  decisionId: z.string().min(1),
  correlationId: z.string().min(1),
  status: z.enum(['pending', 'answered', 'expired', 'cancelled']),
})

const resumeSchema = z.object({
  correlationId: z.string().min(1),
  status: z.enum(['answered', 'expired', 'cancelled']).default('answered'),
  answer: z.string().max(5000).nullable(),
})

export type PusharyInterruptResume = z.input<typeof resumeSchema>

export const prepareReview = (input: PusharyAskInput): PusharyAskInput => {
  const reviewed = { ...input, ...reviewSchema.parse(input) }
  if (reviewed.type === 'select' && !reviewed.options?.length) throw new Error('Pushary: select requires options.')
  if (reviewed.callbackUrl && !reviewed.idempotencyKey) throw new Error('Pushary: durable review requires an operation idempotencyKey.')
  return reviewed.idempotencyKey
    ? { ...reviewed, idempotencyKey: decisionFingerprint(reviewed) }
    : reviewed
}

export const parseReviewAnswer = (answer: unknown, input: PusharyAskInput): string => {
  const value = z.string().min(1).max(5000).parse(answer)
  if ((input.type ?? 'confirm') === 'confirm') return z.enum(['yes', 'no']).parse(value)
  if (input.type === 'select' && !input.options?.includes(value)) throw new Error('Pushary: answer must match an offered option.')
  return value
}

export const parseReviewResume = (resumed: unknown, correlationId: string, input: PusharyAskInput): string | null => {
  const value = resumeSchema.parse(resumed)
  if (value.correlationId !== correlationId) throw new Error('Pushary: resumed answer belongs to another decision.')
  if (value.status !== 'answered') {
    if (value.answer !== null) throw new Error('Pushary: an expired or cancelled review cannot carry an answer.')
    return null
  }
  return parseReviewAnswer(value.answer, input)
}
