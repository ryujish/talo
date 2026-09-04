import { readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { NextResponse } from 'next/server';

const envByProvider = {
  GPT: 'OPENAI_API_KEY',
  Claude: 'ANTHROPIC_API_KEY',
  Gemini: 'GEMINI_API_KEY',
  Grok: 'XAI_API_KEY',
  Kimi: 'MOONSHOT_API_KEY',
  'OpenCode Zen': 'OPENCODE_ZEN_API_KEY',
} as const;

export async function POST(request: Request) {
  if (process.env.NODE_ENV !== 'development') return NextResponse.json({ error: { message: '개발 환경에서만 사용할 수 있습니다.' } }, { status: 404 });

  const body = (await request.json().catch(() => null)) as { accounts?: Array<{ provider?: string; apiKey?: string; isDefault?: boolean }> } | null;
  const accounts = body?.accounts?.filter((account): account is { provider: keyof typeof envByProvider; apiKey: string; isDefault: true } => Boolean(account.isDefault && account.apiKey?.trim() && account.provider && account.provider in envByProvider)) ?? [];
  if (!accounts.length) return NextResponse.json({ saved: 0 });

  const file = path.join(process.cwd(), '.env.local');
  const current = await readFile(file, 'utf8').catch(() => '');
  const keys = new Set(accounts.map((account) => envByProvider[account.provider]));
  const retained = current.split(/\r?\n/).filter((line) => ![...keys].some((key) => line.startsWith(`${key}=`))).filter(Boolean);

  for (const account of accounts) {
    const key = envByProvider[account.provider];
    const value = account.apiKey.trim().replace(/[\r\n]/g, '');
    retained.push(`${key}=${JSON.stringify(value)}`);
    process.env[key] = value;
  }

  const next = `${retained.join('\n')}\n`;
  if (next !== current) {
    const temp = `${file}.tmp`;
    await writeFile(temp, next, { mode: 0o600 });
    await rename(temp, file);
  }

  return NextResponse.json({ saved: accounts.length });
}
