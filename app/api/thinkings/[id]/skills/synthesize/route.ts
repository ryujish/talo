import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { updateDb } from '@/lib/server/db';
import { synthesizeSkillFromSession } from '@/lib/server/skill-synthesis';
import type { InternalAgentRole } from '@/lib/types';

type RouteContext = { params: Promise<{ id: string }> };

export async function POST(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const { id } = await context.params;
  const body = (await request.json().catch(() => ({}))) as {
    name?: string;
    description?: string;
    role?: InternalAgentRole;
    customGuidelines?: string[];
  };

  try {
    const synthesizedSkill = await updateDb((db) => {
      const thinking = db.thinkings.find((t) => t.id === id && t.userId === auth.user.id);
      if (!thinking) return null;

      return synthesizeSkillFromSession(db, {
        userId: auth.user.id,
        sessionId: thinking.thinkalongSessionId,
        name: body.name,
        description: body.description,
        role: body.role,
        customGuidelines: body.customGuidelines,
      });
    });

    if (!synthesizedSkill) {
      return NextResponse.json(
        { error: { code: 'THINKING_NOT_FOUND', message: 'Thinking 세션을 찾을 수 없습니다.' } },
        { status: 404 }
      );
    }

    return NextResponse.json({ skill: synthesizedSkill }, { status: 201 });
  } catch (error) {
    const message = error instanceof Error ? error.message : '스킬 합성에 실패했습니다.';
    return NextResponse.json(
      { error: { code: 'SKILL_SYNTHESIS_FAILED', message } },
      { status: 400 }
    );
  }
}
