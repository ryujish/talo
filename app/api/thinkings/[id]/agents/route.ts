import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { generateThinking } from '@/lib/server/ai';
import { getSkills } from '@/lib/server/capabilities';
import { createContextPacket } from '@/lib/server/context-engine';
import { updateDb, readDb } from '@/lib/server/db';
import { recordEvent } from '@/lib/server/events';
import { getInternalAgentInstruction } from '@/lib/server/internal-agents';
import { requireUser } from '@/lib/server/auth';
import type { InternalAgentRole, SkillId } from '@/lib/types';

type RouteContext = { params: Promise<{ id: string }> };
const roles: InternalAgentRole[] = ['thinker', 'critic', 'synthesizer'];

export async function POST(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;
  const { id } = await context.params;
  const body = (await request.json().catch(() => null)) as { prompt?: string; role?: InternalAgentRole; skillId?: SkillId; apiKey?: string } | null;
  const db = await readDb();
  const availableSkills = getSkills(db);
  const skill = body?.skillId ? availableSkills.find((item) => item.id === body.skillId) : undefined;
  const role = skill?.agentRole ?? body?.role;
  if (!body?.prompt?.trim() || !role || !roles.includes(role) || (body.skillId && !skill)) {
    return NextResponse.json({ error: { code: 'INVALID_AGENT_REQUEST', message: '역할과 요청을 확인해주세요.' } }, { status: 400 });
  }

  const thinking = db.thinkings.find((item) => item.id === id && item.userId === auth.user.id);
  if (!thinking) return NextResponse.json({ error: { code: 'THINKING_NOT_FOUND', message: 'Thinking을 찾을 수 없습니다.' } }, { status: 404 });
  const packet = createContextPacket({ thinkalongSessionId: thinking.thinkalongSessionId, messages: db.messages, decisions: db.decisions, summary: thinking.sessionSummary, prompt: body.prompt });
  
  let agentInstruction = getInternalAgentInstruction(role);
  if (skill?.guidelines && skill.guidelines.length > 0) {
    agentInstruction += `\n\n[Applied Skill: ${skill.name}]\n` + skill.guidelines.map((g) => `- ${g}`).join('\n');
  }
  packet.system = `${packet.system}\n${agentInstruction}`;
  const ai = await generateThinking({ prompt: body.prompt, provider: thinking.aiProvider, context: packet, apiKey: body.apiKey, model: thinking.selectedModel });
  const now = new Date().toISOString();
  const run = await updateDb((mutableDb) => {
    const item = { id: randomUUID(), userId: auth.user.id, thinkalongSessionId: thinking.thinkalongSessionId, role, skillId: skill?.id, contextVersion: packet.version, status: 'completed' as const, output: ai.answer, createdAt: now };
    mutableDb.subAgentRuns.push(item);
    recordEvent(mutableDb, { id: randomUUID(), userId: auth.user.id, thinkalongSessionId: thinking.thinkalongSessionId, type: 'subagent.completed', data: { role, contextVersion: packet.version }, createdAt: now });
    return item;
  });
  return NextResponse.json({ run }, { status: 201 });
}
