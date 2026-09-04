import { NextResponse } from 'next/server';
import { getAiProviderStatuses, getProviderCatalog } from '@/lib/server/ai';
import { requireUser } from '@/lib/server/auth';

export async function GET(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  return NextResponse.json({ providers: getAiProviderStatuses(), catalog: getProviderCatalog() });
}
