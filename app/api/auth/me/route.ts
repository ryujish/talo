import { NextResponse } from 'next/server';
import { currentUser } from '@/lib/server/auth';
import { publicUser } from '@/lib/server/db';

export async function GET(request: Request) {
  const user = await currentUser(request);
  return NextResponse.json({ user: user ? publicUser(user) : null });
}
