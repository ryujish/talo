import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';

export async function POST(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const body = (await request.json().catch(() => null)) as { apiKey?: string } | null;
  if (!body?.apiKey?.trim()) return NextResponse.json({ error: { message: 'OpenCode Zen API Key가 필요합니다.' } }, { status: 400 });

  const response = await fetch('https://opencode.ai/zen/v1/models', {
    headers: { Authorization: `Bearer ${body.apiKey.trim()}` },
    cache: 'no-store',
  });
  const payload = (await response.json().catch(() => null)) as { data?: Array<{ id?: string; name?: string }>; error?: { message?: string } } | null;
  if (!response.ok) return NextResponse.json({ error: { message: payload?.error?.message ?? 'OpenCode Zen 모델 목록을 불러오지 못했습니다.' } }, { status: 400 });

  return NextResponse.json({ models: (payload?.data ?? []).filter((item) => item.id && !/^(grok-|mimo-|kimi-)/.test(item.id)).map((item) => ({ id: item.id!, name: item.name ?? item.id! })) });
}
