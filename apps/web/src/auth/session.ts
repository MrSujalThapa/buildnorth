import { normalizePublishableKey } from "./clerkScript";

export type HostedUsage = {
  enabled: boolean;
  quota_usd: number;
  quota_tokens: number;
  reserved_usd: number;
  spent_usd: number;
  reserved_tokens: number;
  spent_tokens: number;
  remaining_usd: number;
  remaining_tokens: number;
  global_remaining_usd: number | null;
  hosted_available?: boolean;
  kill_switch: boolean;
  billing_note: string;
};

export type UserProfile = {
  display_name: string | null;
  username: string | null;
  bio: string | null;
  avatar_value: string | null;
  dimensions: { label: string; goal_ids: string[] }[];
  parameter_ids?: string[];
};

export type AccountView = {
  user_id: string;
  clerk_user_id: string;
  email: string | null;
  email_verified: boolean;
  role: "user" | "admin";
  invited: boolean;
  hosted: HostedUsage;
  profile?: UserProfile;
};

const TEST_TOKEN_KEY = "pm-test-token";
const INVITE_TOKEN_KEY = "pm-invite-token";

export function clerkEnabled(): boolean {
  return (
    Boolean(normalizePublishableKey(import.meta.env.VITE_CLERK_PUBLISHABLE_KEY)) &&
    import.meta.env.VITE_AUTH_BYPASS !== "true" &&
    import.meta.env.MODE !== "test"
  );
}

export function readTestToken(): string | null {
  if (typeof window === "undefined") return import.meta.env.VITE_TEST_AUTH_TOKEN || null;
  return window.sessionStorage.getItem(TEST_TOKEN_KEY) || import.meta.env.VITE_TEST_AUTH_TOKEN || null;
}

export function writeTestToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.sessionStorage.setItem(TEST_TOKEN_KEY, token);
  else window.sessionStorage.removeItem(TEST_TOKEN_KEY);
}

let tokenProvider: (() => Promise<string | null>) | null = null;

export function setAccessTokenProvider(provider: (() => Promise<string | null>) | null): void {
  tokenProvider = provider;
}

export async function currentAccessToken(): Promise<string | null> {
  if (tokenProvider) return tokenProvider();
  return readTestToken();
}

export function invitePath(token: string): string {
  return `/invite/${encodeURIComponent(token)}`;
}

export function capturePendingInvite(): string | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get("token")?.trim();
  const match = window.location.pathname.match(/^\/invite\/([^/]+)/);
  const fromPath = match?.[1] ? decodeURIComponent(match[1]).trim() : "";
  const token = fromQuery || fromPath;
  if (token) window.sessionStorage.setItem(INVITE_TOKEN_KEY, token);
  return window.sessionStorage.getItem(INVITE_TOKEN_KEY);
}

export function readPendingInvite(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(INVITE_TOKEN_KEY);
}

export function clearPendingInvite(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(INVITE_TOKEN_KEY);
}
