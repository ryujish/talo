import { NextResponse } from 'next/server';
import { sessionCookie, signInWithEmail } from '@/lib/server/auth';
import type { AiProvider } from '@/lib/types';

const validProviders: AiProvider[] = ['GPT', 'Claude', 'Gemini', 'Grok', 'Kimi', 'OpenCode Zen'];

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as {
    email?: string;
    nickname?: string;
    interests?: string[];
    defaultAiProvider?: AiProvider;
  } | null;

  if (!body?.email || !body.email.includes('@')) {
    return NextResponse.json(
      { error: { code: 'INVALID_EMAIL', message: '올바른 이메일을 입력해주세요.' } },
      { status: 400 },
    );
  }

  const result = await signInWithEmail({
    email: body.email,
    nickname: body.nickname,
    interests: body.interests,
    defaultAiProvider: validProviders.includes(body.defaultAiProvider as AiProvider)
      ? body.defaultAiProvider
      : undefined,
  });
  const response = NextResponse.json({ user: result.user });
  response.headers.set('Set-Cookie', sessionCookie(result.token));
  return response;
}
