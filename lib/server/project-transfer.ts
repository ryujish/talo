import type { AppDatabase, Thinking } from '@/lib/types';

export function createProjectExport(db: AppDatabase, thinking: Thinking) {
  const sessionId = thinking.thinkalongSessionId;
  return {
    version: 1,
    exportedAt: new Date().toISOString(),
    thinking,
    messages: db.messages.filter((item) => item.thinkalongSessionId === sessionId),
    attachments: db.attachments.filter((item) => item.thinkalongSessionId === sessionId),
    decisions: db.decisions.filter((item) => item.thinkalongSessionId === sessionId),
    contextSnapshots: db.contextSnapshots.filter((item) => item.thinkalongSessionId === sessionId),
    events: db.events.filter((item) => item.thinkalongSessionId === sessionId),
    toolRuns: db.toolRuns.filter((item) => item.thinkalongSessionId === sessionId),
    subAgentRuns: db.subAgentRuns.filter((item) => item.thinkalongSessionId === sessionId),
  };
}

export function importProject(db: AppDatabase, userId: string, value: unknown) {
  if (!value || typeof value !== 'object') return { error: 'INVALID_IMPORT' } as const;
  const bundle = value as ReturnType<typeof createProjectExport>;
  if (bundle.version !== 1 || !bundle.thinking?.id || !bundle.thinking.thinkalongSessionId ||
      !Array.isArray(bundle.messages) || !Array.isArray(bundle.attachments) || !Array.isArray(bundle.decisions) || !Array.isArray(bundle.contextSnapshots) || !Array.isArray(bundle.events) || !Array.isArray(bundle.toolRuns) || !Array.isArray(bundle.subAgentRuns)) {
    return { error: 'INVALID_IMPORT' } as const;
  }
  if (db.thinkings.some((item) => item.id === bundle.thinking.id)) return { error: 'IMPORT_CONFLICT' } as const;

  const sessionId = bundle.thinking.thinkalongSessionId;
  if ([...bundle.messages, ...bundle.attachments, ...bundle.decisions, ...bundle.contextSnapshots, ...bundle.events, ...bundle.toolRuns, ...bundle.subAgentRuns].some((item) => item.thinkalongSessionId !== sessionId)) {
    return { error: 'INVALID_IMPORT' } as const;
  }
  const thinking = { ...bundle.thinking, userId, contextPolicy: { ...(bundle.thinking.contextPolicy ?? { allowedProviders: ['GPT', 'Claude', 'Gemini', 'Grok', 'Kimi', 'OpenCode Zen'], includeDecisions: true, includeRecentMessages: true }), routingMode: 'manual' as const } };
  db.thinkings.push(thinking);
  db.messages.push(...bundle.messages);
  db.attachments.push(...bundle.attachments);
  db.decisions.push(...bundle.decisions.map((item) => ({ ...item, userId })));
  db.contextSnapshots.push(...bundle.contextSnapshots.map((item) => ({ ...item, userId })));
  db.events.push(...bundle.events.map((item) => ({ ...item, userId })));
  db.toolRuns.push(...bundle.toolRuns.map((item) => ({ ...item, userId })));
  db.subAgentRuns.push(...bundle.subAgentRuns.map((item) => ({ ...item, userId })));
  return { thinking } as const;
}
