import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { inspectSessionContext, tools } from '@/lib/server/capabilities';
import { recordEvent } from '@/lib/server/events';
import { updateDb } from '@/lib/server/db';

type RouteContext = { params: Promise<{ id: string }> };

export async function POST(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;
  const { id } = await context.params;
  const body = (await request.json().catch(() => null)) as { toolId?: string } | null;
  if (!tools.some((tool) => tool.id === body?.toolId)) {
    return NextResponse.json({ error: { code: 'TOOL_NOT_ALLOWED', message: '허용되지 않은 Tool입니다.' } }, { status: 403 });
  }

  const result = await updateDb((db) => {
    const thinking = db.thinkings.find((item) => item.id === id && item.userId === auth.user.id);
    if (!thinking) return null;
    const now = new Date().toISOString();
    const inspected = inspectSessionContext(db, thinking.thinkalongSessionId);
    db.toolRuns.push({ id: randomUUID(), userId: auth.user.id, thinkalongSessionId: thinking.thinkalongSessionId, toolId: 'session.context.inspect', status: 'succeeded', result: inspected, createdAt: now });
    recordEvent(db, { id: randomUUID(), userId: auth.user.id, thinkalongSessionId: thinking.thinkalongSessionId, type: 'tool.executed', data: { toolId: 'session.context.inspect' }, createdAt: now });
    return inspected;
  });
  if (!result) return NextResponse.json({ error: { code: 'THINKING_NOT_FOUND', message: 'Thinking을 찾을 수 없습니다.' } }, { status: 404 });
  return NextResponse.json({ result });
}
