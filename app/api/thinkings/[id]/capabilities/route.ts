import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { getSkills, tools } from '@/lib/server/capabilities';
import { readDb } from '@/lib/server/db';

type RouteContext = { params: Promise<{ id: string }> };

export async function GET(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;
  const { id } = await context.params;
  const db = await readDb();
  if (!db.thinkings.some((item) => item.id === id && item.userId === auth.user.id)) {
    return NextResponse.json({ error: { code: 'THINKING_NOT_FOUND', message: 'Thinking을 찾을 수 없습니다.' } }, { status: 404 });
  }
  return NextResponse.json({ tools, skills: getSkills(db) });
}
