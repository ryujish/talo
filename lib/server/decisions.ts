import { randomUUID } from 'node:crypto';
import type { AppDatabase, DecisionMemory } from '@/lib/types';

type RecordDecisionInput = Omit<DecisionMemory, 'supersededByDecisionId' | 'createdAt' | 'updatedAt'> & {
  now: string;
};

export function recordDecision(db: AppDatabase, input: RecordDecisionInput) {
  if (input.sourceMessageId && !db.messages.some(
    (message) => message.id === input.sourceMessageId && message.thinkalongSessionId === input.thinkalongSessionId,
  )) return { error: 'SOURCE_MESSAGE_NOT_FOUND' } as const;

  const previous = input.supersedesDecisionId
    ? db.decisions.find((decision) => decision.id === input.supersedesDecisionId && decision.userId === input.userId && decision.thinkalongSessionId === input.thinkalongSessionId)
    : undefined;
  const conflict = input.status === 'confirmed' && input.topic
    ? db.decisions.find((decision) => decision.userId === input.userId && decision.thinkalongSessionId === input.thinkalongSessionId && decision.status === 'confirmed' && decision.topic?.trim().toLowerCase() === input.topic!.trim().toLowerCase() && decision.id !== input.supersedesDecisionId && decision.statement.trim() !== input.statement.trim())
    : undefined;
  if (conflict) return { error: 'DECISION_CONFLICT', conflictDecisionId: conflict.id } as const;
  if (input.supersedesDecisionId && (!previous || previous.status !== 'confirmed' || input.status !== 'confirmed')) {
    return { error: 'DECISION_CANNOT_BE_SUPERSEDED' } as const;
  }

  const decision: DecisionMemory = {
    id: input.id,
    userId: input.userId,
    thinkalongSessionId: input.thinkalongSessionId,
    statement: input.statement,
    topic: input.topic?.trim() || undefined,
    status: input.status,
    sourceMessageId: input.sourceMessageId,
    supersedesDecisionId: input.supersedesDecisionId,
    createdAt: input.now,
    updatedAt: input.now,
  };
  if (previous) {
    previous.status = 'superseded';
    previous.supersededByDecisionId = decision.id;
    previous.updatedAt = input.now;
    db.events.push({ id: randomUUID(), userId: input.userId, thinkalongSessionId: input.thinkalongSessionId, type: 'decision.superseded', data: { previousDecisionId: previous.id, decisionId: decision.id }, createdAt: input.now });
  }
  db.decisions.push(decision);
  db.events.push({ id: randomUUID(), userId: input.userId, thinkalongSessionId: input.thinkalongSessionId, type: 'decision.created', data: { decisionId: decision.id, status: decision.status }, createdAt: input.now });
  return { decision } as const;
}
