import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { readDb } from '@/lib/server/db';
import { createProjectExport } from '@/lib/server/project-transfer';
import type { ExportFormat } from '@/lib/types';

const formats: ExportFormat[] = ['markdown', 'pdf', 'word', 'notion', 'json'];

export async function POST(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const body = (await request.json().catch(() => null)) as {
    thinkingId?: string;
    format?: ExportFormat;
  } | null;

  if (!body?.thinkingId || !formats.includes(body.format as ExportFormat)) {
    return NextResponse.json(
      { error: { code: 'INVALID_EXPORT_REQUEST', message: 'thinkingId와 format이 필요합니다.' } },
      { status: 400 },
    );
  }

  const db = await readDb();
  const thinking = db.thinkings.find((item) => item.id === body.thinkingId && item.userId === auth.user.id);
  if (!thinking) {
    return NextResponse.json(
      { error: { code: 'THINKING_NOT_FOUND', message: 'Thinking을 찾을 수 없습니다.' } },
      { status: 404 },
    );
  }

  if (body.format === 'json') {
    return NextResponse.json({
      export: {
        format: 'json',
        filename: `${thinking.title}.json`,
        mimeType: 'application/json',
        content: JSON.stringify(createProjectExport(db, thinking), null, 2),
      },
    });
  }

  const conversation = db.messages
    .filter((message) => message.thinkalongSessionId === thinking.thinkalongSessionId && message.role !== 'system')
    .map((message) => `### ${message.role === 'user' ? '사용자' : `${message.aiProvider ?? thinking.aiProvider} 응답`}\n\n${message.content}`)
    .join('\n\n');
  const markdown = [
    `# ${thinking.title}`,
    '',
    `- AI: ${thinking.aiProvider}`,
    `- Tags: ${thinking.tags.join(', ')}`,
    '',
    '## Conversation',
    conversation,
    '',
    '## Insight',
    thinking.insight ?? '',
  ].join('\n');

  return NextResponse.json({
    export: {
      format: body.format,
      filename: `${thinking.title}.${body.format === 'markdown' ? 'md' : body.format}`,
      mimeType: body.format === 'markdown' ? 'text/markdown' : 'application/octet-stream',
      content: markdown,
    },
  });
}
