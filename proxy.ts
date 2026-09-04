import { NextRequest, NextResponse } from 'next/server';

const ONBOARDING_COOKIE = 'think_along_onboarding_v1';
const SESSION_COOKIE = 'think_along_session';

export function proxy(request: NextRequest) {
  const onboardingDone = request.cookies.get(ONBOARDING_COOKIE)?.value === 'done';
  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  const isExplicitComplete = request.nextUrl.searchParams.get('onboarding') === 'complete';

  if (onboardingDone || hasSession || isExplicitComplete) {
    const response = NextResponse.next();
    if (isExplicitComplete && !onboardingDone) {
      response.cookies.set(ONBOARDING_COOKIE, 'done', {
        path: '/',
        maxAge: 31536000,
        sameSite: 'lax',
      });
    }
    return response;
  }

  const url = request.nextUrl.clone();
  url.pathname = '/start';
  const response = NextResponse.redirect(url);
  response.headers.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0');
  return response;
}

export function middleware(request: NextRequest) {
  return proxy(request);
}

export default proxy;

export const config = {
  matcher: ['/'],
};

