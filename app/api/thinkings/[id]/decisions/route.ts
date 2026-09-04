import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { recordDecision } from '@/lib/server/decisions';
import { readDb, updateDb } from '@/lib/server/db';
import type { DecisionStatus } from '@/lib/types';

type RouteContext = { params: Promise<{ id: string }> };

export async function GET(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const { id } = await context.params;
  const db = await readDb();
  const thinking = db.thinkings.find((item) => item.id === id && item.userId === auth.user.id);
  if (!thinking) return NextResponse.json({ error: { code: 'THINKING_NOT_FOUND', message: 'Thinking을 찾을 수 없습니다.' } }, { status: 404 });

  return NextResponse.json({
    decisions: db.decisions.filter((decision) => decision.thinkalongSessionId === thinking.thinkalongSessionId),
  });
}

export async function POST(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const { id } = await context.params;
  const body = (await request.json().catch(() => null)) as {
    statement?: string;
    topic?: string;
    status?: DecisionStatus;
    sourceMessageId?: string;
    supersedesDecisionId?: string;
  } | null;
  const status = body?.status ?? 'reviewing';
  if (!body?.statement?.trim() || !['reviewing', 'confirmed'].includes(status)) {
    return NextResponse.json({ error: { code: 'INVALID_DECISION', message: '결정문과 올바른 상태가 필요합니다.' } }, { status: 400 });
  }

  const result = await updateDb((db) => {
    const thinking = db.thinkings.find((item) => item.id === id && item.userId === auth.user.id);
    if (!thinking) return { error: 'THINKING_NOT_FOUND' } as const;
    return recordDecision(db, {
      id: randomUUID(),
      userId: auth.user.id,
      thinkalongSessionId: thinking.thinkalongSessionId,
      statement: body.statement!.trim(),
      topic: body.topic,
      status,
      sourceMessageId: body.sourceMessageId,
      supersedesDecisionId: body.supersedesDecisionId,
      now: new Date().toISOString(),
    });
  });

  if ('error' in result) {
    const notFound = result.error === 'THINKING_NOT_FOUND';
    return NextResponse.json(
      { error: { code: result.error, message: notFound ? 'Thinking을 찾을 수 없습니다.' : result.error === 'DECISION_CONFLICT' ? '같은 주제의 확정 결정과 충돌합니다. 기존 결정을 대체할지 확인해주세요.' : '결정의 출처 또는 대체 관계를 확인해주세요.', ...('conflictDecisionId' in result ? { conflictDecisionId: result.conflictDecisionId } : {}) } },
      { status: notFound ? 404 : 400 },
    );
  }
  return NextResponse.json({ decision: result.decision }, { status: 201 });
}
