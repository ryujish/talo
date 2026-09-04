import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import type { AiProvider, User } from '@/lib/types';
import { publicUser, readDb, updateDb } from './db';

export const sessionCookieName = 'think_along_session';

const hashToken = (token: string) => createHash('sha256').update(token).digest('hex');

export function sessionCookie(token: string) {
  return `${sessionCookieName}=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${60 * 60 * 24 * 30}`;
}

export function clearSessionCookie() {
  return `${sessionCookieName}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`;
}

export function getCookieValue(request: Request, name: string) {
  const cookie = request.headers.get('cookie') ?? '';
  return cookie
    .split(';')
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))
    ?.split('=')
    .slice(1)
    .join('=');
}

export async function signInWithEmail(input: {
  email: string;
  nickname?: string;
  interests?: string[];
  defaultAiProvider?: AiProvider;
}) {
  const normalizedEmail = input.email.trim().toLowerCase();
  const token = randomBytes(32).toString('hex');
  const tokenHash = hashToken(token);
  const expiresAt = new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString();

  const user = await updateDb<User>((db) => {
    let existing = db.users.find((item) => item.email === normalizedEmail);

    if (!existing) {
      existing = {
        id: randomUUID(),
        email: normalizedEmail,
        nickname: input.nickname?.trim() || normalizedEmail.split('@')[0] || 'Thinker',
        authProvider: 'email',
        interests: input.interests?.length ? input.interests : ['사업', '개발'],
        defaultAiProvider: input.defaultAiProvider ?? 'GPT',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      db.users.push(existing);
    } else {
      existing.nickname = input.nickname?.trim() || existing.nickname;
      existing.interests = input.interests?.length ? input.interests : existing.interests;
      existing.defaultAiProvider = input.defaultAiProvider ?? existing.defaultAiProvider;
      existing.updatedAt = new Date().toISOString();
    }

    db.sessions = db.sessions.filter(
      (session) => session.userId !== existing.id || new Date(session.expiresAt).getTime() > Date.now(),
    );
    db.sessions.push({
      id: randomUUID(),
      userId: existing.id,
      tokenHash,
      expiresAt,
      createdAt: new Date().toISOString(),
    });

    return existing;
  });

  return { token, user: publicUser(user) };
}

export async function currentUser(request: Request) {
  const token = getCookieValue(request, sessionCookieName);
  if (!token) return null;

  const db = await readDb();
  const session = db.sessions.find((item) => item.tokenHash === hashToken(token));
  if (!session || new Date(session.expiresAt).getTime() <= Date.now()) return null;

  const user = db.users.find((item) => item.id === session.userId);
  return user ?? null;
}

export async function requireUser(request: Request) {
  const user = await currentUser(request);

  if (!user) {
    return {
      user: null,
      response: NextResponse.json(
        { error: { code: 'AUTH_REQUIRED', message: '로그인이 필요합니다.' } },
        { status: 401 },
      ),
    };
  }

  return { user, response: null };
}
