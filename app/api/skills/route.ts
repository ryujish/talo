import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { readDb, updateDb } from '@/lib/server/db';
import { getAllSkills } from '@/lib/server/skill-synthesis';
import type { InternalAgentRole, SkillDefinition, ToolId } from '@/lib/types';
import { randomUUID } from 'node:crypto';

export async function GET(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const db = await readDb();
  const skills = getAllSkills(db);

  return NextResponse.json({ skills });
}

export async function POST(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const body = (await request.json().catch(() => null)) as {
    name?: string;
    description?: string;
    guidelines?: string[];
    agentRole?: InternalAgentRole;
    allowedTools?: ToolId[];
  } | null;

  if (!body?.name?.trim() || !body.agentRole) {
    return NextResponse.json(
      { error: { code: 'INVALID_SKILL_PAYLOAD', message: '스킬 이름과 에이전트 역할은 필수입니다.' } },
      { status: 400 }
    );
  }

  const now = new Date().toISOString();
  const newSkill: SkillDefinition = {
    id: `skill_${randomUUID().slice(0, 8)}`,
    name: body.name.trim(),
    description: body.description?.trim(),
    guidelines: body.guidelines ?? [],
    agentRole: body.agentRole,
    allowedTools: body.allowedTools ?? ['session.context.inspect'],
    createdAt: now,
  };

  await updateDb((db) => {
    db.skills ??= [];
    db.skills.push(newSkill);
  });

  return NextResponse.json({ skill: newSkill }, { status: 201 });
}
