import { randomUUID } from 'node:crypto';
import type { AppDatabase, InternalAgentRole, SkillDefinition, ToolId } from '@/lib/types';
import { recordEvent } from '@/lib/server/events';
import { skills as defaultSkills } from '@/lib/server/capabilities';

export type SynthesizeSkillInput = {
  userId: string;
  sessionId: string;
  name?: string;
  description?: string;
  role?: InternalAgentRole;
  customGuidelines?: string[];
};

/**
 * Returns all active skills including built-in static skills and dynamically synthesized skills.
 */
export function getAllSkills(db: AppDatabase): SkillDefinition[] {
  const dynamicSkills = db.skills ?? [];
  const map = new Map<string, SkillDefinition>();

  for (const s of defaultSkills) {
    map.set(s.id, s);
  }
  for (const s of dynamicSkills) {
    map.set(s.id, s);
  }

  return Array.from(map.values());
}

/**
 * Closed Learning Loop:
 * Synthesizes a reusable procedural Skill from a session's confirmed decisions,
 * user interactions, and executed tools.
 */
export function synthesizeSkillFromSession(
  db: AppDatabase,
  input: SynthesizeSkillInput
): SkillDefinition {
  const thinking = db.thinkings.find((t) => t.thinkalongSessionId === input.sessionId && t.userId === input.userId);
  if (!thinking) {
    throw new Error(`Thinking session not found for id: ${input.sessionId}`);
  }

  const confirmedDecisions = db.decisions.filter(
    (d) => d.thinkalongSessionId === input.sessionId && d.status === 'confirmed'
  );

  const toolRuns = db.toolRuns.filter(
    (t) => t.thinkalongSessionId === input.sessionId && t.status === 'succeeded'
  );

  const allowedTools: ToolId[] = Array.from(new Set(toolRuns.map((t) => t.toolId)));
  if (allowedTools.length === 0) {
    allowedTools.push('session.context.inspect');
  }

  // Synthesize procedural guidelines from confirmed decisions and session context
  const guidelines: string[] = [];
  if (input.customGuidelines && input.customGuidelines.length > 0) {
    guidelines.push(...input.customGuidelines);
  } else {
    for (const d of confirmedDecisions) {
      guidelines.push(`[확정 원칙] ${d.statement}`);
    }
    if (thinking.insight) {
      guidelines.push(`[사고 패턴] ${thinking.insight}`);
    }
    if (guidelines.length === 0) {
      guidelines.push(`[절차 가이드] 세션 '${thinking.title}'의 핵심 맥락과 제약을 우선 준수한다.`);
    }
  }

  const now = new Date().toISOString();
  const skillId = `skill_${randomUUID().slice(0, 8)}`;
  const synthesizedSkill: SkillDefinition = {
    id: skillId,
    name: input.name?.trim() || `${thinking.title} 노하우 스킬`,
    description:
      input.description?.trim() ||
      `세션 '${thinking.title}'의 ${confirmedDecisions.length}개 확정 결정 및 대화 경험에서 합성된 재사용 스킬입니다.`,
    guidelines,
    agentRole: input.role || 'synthesizer',
    allowedTools,
    synthesizedFromSessionId: input.sessionId,
    createdAt: now,
  };

  db.skills ??= [];
  db.skills.push(synthesizedSkill);

  recordEvent(db, {
    id: randomUUID(),
    userId: input.userId,
    thinkalongSessionId: input.sessionId,
    type: 'skill.synthesized',
    data: {
      skillId: synthesizedSkill.id,
      skillName: synthesizedSkill.name,
      decisionCount: confirmedDecisions.length,
    },
    createdAt: now,
  });

  return synthesizedSkill;
}
