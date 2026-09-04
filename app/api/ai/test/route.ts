import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';

const endpoints = {
  GPT: (model: string, apiKey: string) => ({
    url: `https://api.openai.com/v1/models/${encodeURIComponent(model)}`,
    headers: { Authorization: `Bearer ${apiKey}` },
  }),
  Claude: (model: string, apiKey: string) => ({
    url: `https://api.anthropic.com/v1/models/${encodeURIComponent(model)}`,
    headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
  }),
  Gemini: (model: string, apiKey: string) => ({
    url: `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}?key=${encodeURIComponent(apiKey)}`,
    headers: {},
  }),
  Grok: (model: string, apiKey: string) => ({
    url: 'https://api.x.ai/v1/responses',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, input: 'Reply OK.' }),
  }),
  Kimi: (_model: string, apiKey: string) => ({
    url: 'https://api.moonshot.ai/v1/models',
    headers: { Authorization: `Bearer ${apiKey}` },
  }),
  'OpenCode Zen': (model: string, apiKey: string) => ({
    url: /^(gpt-|grok-|muse-spark)/.test(model) ? 'https://opencode.ai/zen/v1/responses' : 'https://opencode.ai/zen/v1/chat/completions',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(/^(gpt-|grok-|muse-spark)/.test(model)
      ? { model, input: 'Reply OK.', max_output_tokens: 1 }
      : { model, messages: [{ role: 'user', content: 'Reply OK.' }], max_tokens: 1 }),
  }),
} satisfies Record<string, (model: string, apiKey: string) => { url: string; headers: Record<string, string>; body?: string }>;

export async function POST(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const body = (await request.json().catch(() => null)) as { provider?: keyof typeof endpoints; apiKey?: string; model?: string } | null;
  if (!body?.provider || !body.apiKey?.trim() || !body.model?.trim() || !endpoints[body.provider]) {
    return NextResponse.json({ error: { code: 'INVALID_REQUEST', message: 'Provider, API Key, 모델이 필요합니다.' } }, { status: 400 });
  }

  const target: { url: string; headers: Record<string, string>; body?: string } = endpoints[body.provider](body.model, body.apiKey.trim());
  const response = await fetch(target.url, { method: target.body ? 'POST' : 'GET', headers: target.headers, body: target.body, cache: 'no-store' });
  if (response.ok) return NextResponse.json({ connected: true });

  if (body.provider === 'Grok' && response.status === 403) {
    return NextResponse.json({ error: { code: 'XAI_PERMISSION_DENIED', message: 'xAI API Key에 Grok 모델 또는 Responses API 권한이 없습니다. xAI Console에서 모델·엔드포인트 권한과 팀 결제 상태를 확인해주세요.' } }, { status: 400 });
  }

  const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
  const rawMessage = payload?.error?.message ?? `Provider 연결 실패 (${response.status})`;
  const message = /Endpoint is unavailable|Upstream request failed/i.test(rawMessage)
    ? '선택한 OpenCode Zen 모델을 일시적으로 사용할 수 없습니다. API Key 문제가 아니므로 Big Pickle 또는 Ox Alpha로 바꾸어 다시 시도해주세요.'
    : rawMessage;
  return NextResponse.json({ error: { code: 'PROVIDER_CONNECTION_FAILED', message } }, { status: 400 });
}
