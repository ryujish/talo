import type { AppDatabase, SkillDefinition, ToolDefinition } from '@/lib/types';

export const tools: ToolDefinition[] = [
  { id: 'session.context.inspect', name: '현재 Context 범위 확인', risk: 'read' },
];

export const skills: SkillDefinition[] = [
  { id: 'decision-review', name: '확정 결정 검토', agentRole: 'critic', allowedTools: ['session.context.inspect'], description: '현재 세션의 확정 결정 충돌 여부 및 근거를 검토합니다.' },
];

export function getSkills(db?: AppDatabase): SkillDefinition[] {
  const dynamicSkills = db?.skills ?? [];
  const map = new Map<string, SkillDefinition>();
  for (const s of skills) map.set(s.id, s);
  for (const s of dynamicSkills) map.set(s.id, s);
  return Array.from(map.values());
}

export function inspectSessionContext(db: AppDatabase, sessionId: string) {
  return {
    messages: db.messages.filter((item) => item.thinkalongSessionId === sessionId).length,
    decisions: db.decisions.filter((item) => item.thinkalongSessionId === sessionId && item.status === 'confirmed').length,
    snapshots: db.contextSnapshots.filter((item) => item.thinkalongSessionId === sessionId).length,
  };
}

