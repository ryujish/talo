import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { discoverAiEnvironment } from '@/lib/server/ai-discovery';
import { getAiProviderStatuses } from '@/lib/server/ai';

export async function GET(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;
  return NextResponse.json({ local: await discoverAiEnvironment(), server: getAiProviderStatuses() });
}
