/**
 * Auth helper utilities.
 *
 * Provides JWT parsing, current-user extraction, authentication checks,
 * and logout helpers backed by localStorage.
 *
 * Requirements: 1.1, 1.2, 1.3
 */

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserInfo {
  user_id: string;
  role: 'investigator' | 'supervisor' | 'admin';
  email: string;
}

/** Decode a JWT payload from the base64url-encoded middle segment. */
export function parseJwt(token: string): Record<string, unknown> | null {
  try {
    const [, payloadB64] = token.split('.');
    if (!payloadB64) return null;

    // base64url → base64 → JSON
    const padded = payloadB64.replace(/-/g, '+').replace(/_/g, '/');
    const json = atob(padded);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Read the access token from localStorage and extract the user info embedded
 * in the JWT payload (sub, role).
 *
 * Returns null when no token is present or the token cannot be parsed.
 */
export function getCurrentUser(): UserInfo | null {
  if (typeof window === 'undefined') return null;

  const token = localStorage.getItem('access_token');
  if (!token) return null;

  const payload = parseJwt(token);
  if (!payload) return null;

  const sub = payload['sub'];
  const role = payload['role'];
  const email = payload['email'] ?? `${sub}`;

  if (typeof sub !== 'string' || typeof role !== 'string') return null;

  const validRoles = ['investigator', 'supervisor', 'admin'] as const;
  if (!validRoles.includes(role as (typeof validRoles)[number])) return null;

  return {
    user_id: sub,
    role: role as UserInfo['role'],
    email: typeof email === 'string' ? email : String(sub),
  };
}

/**
 * Return true when a valid, non-expired access token exists in localStorage.
 *
 * Expiry is checked against the JWT `exp` claim (UNIX seconds) so the check
 * is purely client-side — no network request is made.
 */
export function isAuthenticated(): boolean {
  if (typeof window === 'undefined') return false;

  const token = localStorage.getItem('access_token');
  if (!token) return false;

  const payload = parseJwt(token);
  if (!payload) return false;

  const exp = payload['exp'];
  if (typeof exp !== 'number') return false;

  // Add a small 10-second buffer so near-expired tokens are treated as expired
  return Date.now() / 1000 < exp - 10;
}

/**
 * Persist a token pair to localStorage.
 */
export function storeTokens(pair: TokenPair): void {
  localStorage.setItem('access_token', pair.access_token);
  localStorage.setItem('refresh_token', pair.refresh_token);
}

/**
 * Clear tokens from localStorage and redirect to the login page.
 */
export function logout(): void {
  if (typeof window === 'undefined') return;

  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  window.location.href = '/auth/login';
}
