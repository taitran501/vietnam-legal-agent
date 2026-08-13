export interface AuthSession {
  accessToken: string;
  expiresAt: number;
}

const SESSION_KEY = 'epr-oidc-session';
const STATE_KEY = 'epr-oidc-state';
const VERIFIER_KEY = 'epr-oidc-verifier';
const RETURN_TO_KEY = 'epr-oidc-return-to';
export const AUTH_EXPIRED_EVENT = 'epr-auth-expired';

function issuer(): string {
  return String(import.meta.env.VITE_OIDC_ISSUER || '').replace(/\/$/, '');
}

export function isOidcConfigured(): boolean {
  return Boolean(issuer() && import.meta.env.VITE_OIDC_CLIENT_ID);
}

export function getAuthSession(): AuthSession | null {
  if (!isOidcConfigured()) return null;
  const raw = sessionStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    const session = JSON.parse(raw) as AuthSession;
    if (!session.accessToken || session.expiresAt <= Date.now() / 1000 + 15) {
      sessionStorage.removeItem(SESSION_KEY);
      return null;
    }
    return session;
  } catch {
    sessionStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function clearAuthSession(): void {
  sessionStorage.removeItem(SESSION_KEY);
}

export function rememberReturnTo(): void {
  const target = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (!target.includes('code=') && target.startsWith('/')) {
    sessionStorage.setItem(RETURN_TO_KEY, target);
  }
}

export function handleUnauthorized(): void {
  rememberReturnTo();
  clearAuthSession();
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
}

function encode(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function createVerifier(): Promise<string> {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return encode(bytes);
}

async function challenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return encode(new Uint8Array(digest));
}

async function discovery(): Promise<{ authorization_endpoint: string; token_endpoint: string }> {
  const response = await fetch(`${issuer()}/.well-known/openid-configuration`, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error('Không thể tải cấu hình đăng nhập SSO');
  return response.json() as Promise<{ authorization_endpoint: string; token_endpoint: string }>;
}

export async function beginLogin(): Promise<void> {
  if (!isOidcConfigured()) return;
  rememberReturnTo();
  const config = await discovery();
  const state = await createVerifier();
  const verifier = await createVerifier();
  sessionStorage.setItem(STATE_KEY, state);
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  const params = new URLSearchParams({
    client_id: String(import.meta.env.VITE_OIDC_CLIENT_ID),
    response_type: 'code',
    redirect_uri: String(import.meta.env.VITE_OIDC_REDIRECT_URI || window.location.origin),
    scope: String(import.meta.env.VITE_OIDC_SCOPE || 'openid profile email'),
    state,
    code_challenge: await challenge(verifier),
    code_challenge_method: 'S256',
  });
  window.location.assign(`${config.authorization_endpoint}?${params.toString()}`);
}

export async function completeLogin(): Promise<AuthSession | null> {
  if (!isOidcConfigured()) return null;
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  if (!code) return getAuthSession();
  const expectedState = sessionStorage.getItem(STATE_KEY);
  if (!expectedState || params.get('state') !== expectedState) throw new Error('Phiên đăng nhập SSO không hợp lệ');
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!verifier) throw new Error('Thiếu mã xác minh PKCE');
  const config = await discovery();
  const response = await fetch(config.token_endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: String(import.meta.env.VITE_OIDC_CLIENT_ID),
      redirect_uri: String(import.meta.env.VITE_OIDC_REDIRECT_URI || window.location.origin),
      code,
      code_verifier: verifier,
    }),
  });
  if (!response.ok) throw new Error('Đăng nhập SSO thất bại');
  const payload = await response.json() as { access_token: string; expires_in?: number };
  const session: AuthSession = {
    accessToken: payload.access_token,
    expiresAt: Math.floor(Date.now() / 1000) + Number(payload.expires_in || 3600),
  };
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  sessionStorage.removeItem(STATE_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  const returnTo = sessionStorage.getItem(RETURN_TO_KEY) || '/';
  sessionStorage.removeItem(RETURN_TO_KEY);
  window.history.replaceState({}, document.title, returnTo.startsWith('/') ? returnTo : '/');
  return session;
}

export function authorizationHeader(): Record<string, string> {
  const session = getAuthSession();
  return session ? { Authorization: `Bearer ${session.accessToken}` } : {};
}
