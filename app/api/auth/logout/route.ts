import { NextResponse } from 'next/server';
import { clearSessionCookie, getCookieValue, sessionCookieName } from '@/lib/server/auth';
import { updateDb } from '@/lib/server/db';
import { createHash } from 'node:crypto';

export async function POST(request: Request) {
  const token = getCookieValue(request, sessionCookieName);

  if (token) {
    const tokenHash = createHash('sha256').update(token).digest('hex');
    await updateDb((db) => {
      db.sessions = db.sessions.filter((session) => session.tokenHash !== tokenHash);
    });
  }

  const response = NextResponse.json({ ok: true });
  response.headers.set('Set-Cookie', clearSessionCookie());
  return response;
}
