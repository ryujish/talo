import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { readDb, updateDb } from '@/lib/server/db';

export async function GET(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const db = await readDb();
  const insights = db.insights
    .filter((insight) => insight.userId === auth.user.id)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  return NextResponse.json({ insights });
}

export async function POST(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const db = await readDb();
  const thinkings = db.thinkings.filter((thinking) => thinking.userId === auth.user.id && thinking.status === 'active');
  const tagCounts = new Map<string, number>();

  for (const thinking of thinkings) {
    for (const tag of thinking.tags) {
      tagCounts.set(tag, (tagCounts.get(tag) ?? 0) + 1);
    }
  }

  const topTags = [...tagCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([tag]) => tag);
  const now = new Date().toISOString();

  const insight = await updateDb((mutableDb) => {
    const created = {
      id: randomUUID(),
      userId: auth.user.id,
      period: 'weekly' as const,
      title: '주간 Insight',
      summary: topTags.length
        ? `최근 Thinking에서 ${topTags.join(', ')} 관심사가 두드러집니다.`
        : '아직 분석할 Thinking이 충분하지 않습니다.',
      patterns: topTags.map((tag) => `${tag} 관련 질문 반복`),
      recommendations: ['핵심 질문을 하나로 좁히기', '다음 액션을 캘린더에 예약하기', '관련 Thinking을 폴더로 묶기'],
      createdAt: now,
    };
    mutableDb.insights.push(created);
    return created;
  });

  return NextResponse.json({ insight }, { status: 201 });
}
