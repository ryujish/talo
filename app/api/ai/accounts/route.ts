import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { readDb, updateDb } from '@/lib/server/db';
import type { AiProvider, ConnectionStatus, ProviderId } from '@/lib/types';

const providerIds: Record<AiProvider, ProviderId> = {
  GPT: 'openai', Claude: 'anthropic', Gemini: 'gemini', Grok: 'xai', Kimi: 'moonshot',
  'OpenCode Zen': 'opencode', 'Hermes Local': 'local',
};
const labels = Object.fromEntries(Object.entries(providerIds).map(([label, id]) => [id, label])) as Record<ProviderId, AiProvider>;

export async function GET(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;
  const db = await readDb();
  const accounts = db.providerConnections.filter((item) => item.userId === auth.user.id && item.credentialRef === 'browser-local').map((item) => ({
    id: item.id, provider: labels[item.provider], name: item.name, model: item.models[0]?.id ?? '',
    isDefault: Boolean(item.isDefault),
    status: item.status === 'available' ? 'connected' : item.status === 'unavailable' ? 'invalid' : 'untested',
    lastCheckedAt: item.lastCheckedAt, source: 'server',
  }));
  return NextResponse.json({ accounts });
}

export async function PUT(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;
  const body = (await request.json().catch(() => null)) as { accounts?: Array<Record<string, unknown>> } | null;
  if (!Array.isArray(body?.accounts) || body.accounts.length > 50) {
    return NextResponse.json({ error: { message: 'accounts 배열이 필요합니다.' } }, { status: 400 });
  }
  const validProviders = new Set(Object.keys(providerIds));
  const accounts = body.accounts.flatMap((item) => {
    const provider = String(item.provider ?? '') as AiProvider;
    const id = String(item.id ?? '').trim();
    const model = String(item.model ?? '').trim();
    if (!validProviders.has(provider) || !/^[\w:.-]{1,120}$/.test(id) || !model || model.length > 160) return [];
    const status: ConnectionStatus = item.status === 'connected' ? 'available' : item.status === 'invalid' ? 'unavailable' : 'unknown';
    return [{ id, userId: auth.user.id, provider: providerIds[provider], name: String(item.name ?? provider).slice(0, 120),
      authKind: 'api_key' as const, credentialRef: 'browser-local', status, models: [{ id: model, text: true as const }],
      isDefault: Boolean(item.isDefault),
      lastCheckedAt: typeof item.lastCheckedAt === 'string' ? item.lastCheckedAt : undefined }];
  });
  await updateDb((db) => {
    db.providerConnections = db.providerConnections.filter((item) => item.userId !== auth.user!.id || item.credentialRef !== 'browser-local');
    db.providerConnections.push(...accounts);
  });
  return NextResponse.json({ saved: accounts.length });
}
