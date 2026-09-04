import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { updateDb } from '@/lib/server/db';
import { importProject } from '@/lib/server/project-transfer';

export async function POST(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const body = (await request.json().catch(() => null)) as { content?: string | object } | null;
  let content: unknown = body?.content;
  if (typeof body?.content === 'string') {
    try { content = JSON.parse(body.content); } catch { content = null; }
  }
  const result = await updateDb((db) => importProject(db, auth.user.id, content));
  if ('error' in result) {
    return NextResponse.json({ error: { code: result.error, message: result.error === 'IMPORT_CONFLICT' ? '같은 프로젝트가 이미 있습니다.' : '올바른 Think Along JSON 파일이 아닙니다.' } }, { status: 400 });
  }
  return NextResponse.json({ thinking: result.thinking }, { status: 201 });
}
