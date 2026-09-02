/**
 * Next.js Edge Middleware — route protection.
 *
 * AUTH IS TEMPORARILY DISABLED — all routes pass through unconditionally.
 * TODO: re-enable with MetaMask wallet-signature auth.
 *
 * Original implementation (JWT cookie / Bearer header check) is preserved
 * below in a comment block for reference.
 *
 * Requirements: 1.1, 16.2
 */

import { NextRequest, NextResponse } from 'next/server';

// ---------------------------------------------------------------------------
// Middleware — pass-through (auth disabled)
// ---------------------------------------------------------------------------

export function middleware(_request: NextRequest): NextResponse {
  return NextResponse.next();
}

// ---------------------------------------------------------------------------
// Matcher — apply middleware to everything except static assets
// ---------------------------------------------------------------------------

export const config = {
  matcher: [
    /*
     * Match all request paths EXCEPT:
     *  - _next/static (static files)
     *  - _next/image  (image optimisation)
     *  - favicon.ico
     */
    '/((?!_next/static|_next/image|favicon\\.ico).*)',
  ],
};

/*
 * ─── ORIGINAL JWT AUTH IMPLEMENTATION (preserved for reference) ───────────
 *
 * function decodeJwtPayload(token: string): Record<string, unknown> | null {
 *   try {
 *     const parts = token.split('.');
 *     if (parts.length !== 3) return null;
 *     const payloadB64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
 *     const json = Buffer.from(payloadB64, 'base64').toString('utf8');
 *     return JSON.parse(json) as Record<string, unknown>;
 *   } catch {
 *     return null;
 *   }
 * }
 *
 * function isTokenValid(token: string): boolean {
 *   const payload = decodeJwtPayload(token);
 *   if (!payload) return false;
 *   const exp = payload['exp'];
 *   if (typeof exp !== 'number') return false;
 *   return Date.now() / 1000 < exp - 10;
 * }
 *
 * function extractToken(request: NextRequest): string | null {
 *   const cookieToken = request.cookies.get('access_token')?.value;
 *   if (cookieToken) return cookieToken;
 *   const authHeader = request.headers.get('Authorization');
 *   if (authHeader?.startsWith('Bearer ')) return authHeader.slice(7);
 *   return null;
 * }
 *
 * const PUBLIC_PREFIXES = ['/auth/', '/_next/', '/favicon.ico', '/api/'];
 *
 * function isPublicRoute(pathname: string): boolean {
 *   if (pathname === '/auth/login' || pathname === '/auth/logout') return true;
 *   return PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix));
 * }
 *
 * export function middleware(request: NextRequest): NextResponse {
 *   const { pathname } = request.nextUrl;
 *   if (isPublicRoute(pathname)) return NextResponse.next();
 *   const token = extractToken(request);
 *   if (!token || !isTokenValid(token)) {
 *     const loginUrl = new URL('/auth/login', request.url);
 *     loginUrl.searchParams.set('next', pathname);
 *     return NextResponse.redirect(loginUrl);
 *   }
 *   return NextResponse.next();
 * }
 * ──────────────────────────────────────────────────────────────────────────
 */
