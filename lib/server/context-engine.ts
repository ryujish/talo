import type { ContextPacket, ConversationMessage, DecisionMemory } from '@/lib/types';

export const THINK_ALONG_SYSTEM_CONTEXT = [
  'You are Think Along.',
  'Maintain continuity across AI providers.',
  'Use only the supplied context; do not invent memory.',
  'Treat provider metadata as execution history, not conversation identity.',
].join('\n');

const MAX_RECENT_MESSAGES = 20;

export function createContextPacket(input: {
  thinkalongSessionId: string;
  messages: ConversationMessage[];
  decisions?: DecisionMemory[];
  includeDecisions?: boolean;
  includeRecentMessages?: boolean;
  summary?: string;
  prompt: string;
}): ContextPacket {
  const sessionMessages = input.messages
    .filter((message) => message.thinkalongSessionId === input.thinkalongSessionId)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id));

  // ponytail: fixed window; replace with token-aware compaction when provider limits require it.
  const recentMessages = sessionMessages.slice(-MAX_RECENT_MESSAGES);
  const sessionDecisions = (input.decisions ?? [])
    .filter((decision) => decision.thinkalongSessionId === input.thinkalongSessionId)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id));

  return {
    thinkalongSessionId: input.thinkalongSessionId,
    version: sessionMessages.length + sessionDecisions.length + 1,
    system: THINK_ALONG_SYSTEM_CONTEXT,
    summary: input.summary,
    decisions: input.includeDecisions === false ? [] : sessionDecisions
      .filter((decision) => decision.status === 'confirmed')
      .map(({ id, statement }) => ({ id, statement })),
    messages: [
      ...(input.includeRecentMessages === false ? [] : recentMessages.map(({ role, content }) => ({ role, content }))),
      { role: 'user', content: input.prompt.trim() },
    ],
  };
}
