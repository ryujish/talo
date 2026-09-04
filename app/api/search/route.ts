import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { readDb } from '@/lib/server/db';

export async function GET(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const db = await readDb();
  const url = new URL(request.url);
  const keyword = (url.searchParams.get('q') ?? '').trim().toLowerCase();
  const ai = url.searchParams.get('ai');
  const tag = url.searchParams.get('tag');
  const folder = url.searchParams.get('folder');
  const favorite = url.searchParams.get('favorite');

  const results = db.thinkings
    .filter((thinking) => thinking.userId === auth.user.id && thinking.status === 'active')
    .filter((thinking) => {
      if (!keyword) return true;
      const haystack = [thinking.title, thinking.prompt, thinking.answer, thinking.insight, thinking.tags.join(' ')]
        .join(' ')
        .toLowerCase();
      return haystack.includes(keyword);
    })
    .filter((thinking) => (ai ? thinking.aiProvider === ai : true))
    .filter((thinking) => (tag ? thinking.tags.includes(tag) : true))
    .filter((thinking) => (folder ? thinking.folder === folder : true))
    .filter((thinking) => (favorite === 'true' ? thinking.favorite : true))
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));

  return NextResponse.json({ results });
}
