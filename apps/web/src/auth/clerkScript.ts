const TEST_PREFIX = "pk_test_";
const LIVE_PREFIX = "pk_live_";
const CLERK_JS_MAJOR = "6";
const CLERK_UI_MAJOR = "1";

export type ClerkLoadOptions = {
  clerkJSUrl: string;
  __internal_clerkJSUrl: string;
  __internal_clerkUIUrl: string;
};

function decodeBase64(value: string): string | null {
  try {
    const padded = value + "=".repeat((4 - (value.length % 4)) % 4);
    const decoded = atob(padded);
    return decoded.endsWith("$") && !decoded.slice(0, -1).includes("$") && decoded.includes(".")
      ? decoded.slice(0, -1)
      : null;
  } catch {
    return null;
  }
}

/** Trim quotes/whitespace and correct a duplicated `p` on `pk_test_` / `pk_live_`. */
export function normalizePublishableKey(raw: string | undefined): string | undefined {
  let key = raw?.trim().replace(/^["']|["']$/g, "") ?? "";
  if (!key) return undefined;
  if (key.startsWith("ppk_test_")) key = `${TEST_PREFIX}${key.slice("ppk_test_".length)}`;
  else if (key.startsWith("ppk_live_")) key = `${LIVE_PREFIX}${key.slice("ppk_live_".length)}`;
  return key || undefined;
}

export function frontendApiFromPublishableKey(raw: string | undefined): string | null {
  const key = normalizePublishableKey(raw);
  if (!key) return null;
  if (key.startsWith(TEST_PREFIX)) return decodeBase64(key.slice(TEST_PREFIX.length));
  if (key.startsWith(LIVE_PREFIX)) return decodeBase64(key.slice(LIVE_PREFIX.length));
  return null;
}

export function isAllowedClerkFrontendHost(host: string): boolean {
  const hostname = host.trim().toLowerCase();
  if (!hostname || hostname.includes("/") || hostname.includes(":") || hostname.includes(" ")) {
    return false;
  }
  if (hostname.endsWith(".clerk.accounts.dev") || hostname.endsWith(".clerk.accounts.com")) {
    return hostname.split(".").length >= 4;
  }
  return hostname.startsWith("clerk.") && hostname.split(".").length >= 3;
}

function scriptUrl(host: string, pkg: "clerk-js" | "ui", major: string, file: string): string {
  return `https://${host}/npm/@clerk/${pkg}@${major}/dist/${file}`;
}

function hostFromOverride(override: string | undefined, expectedHost: string): string | null {
  if (!override?.trim()) return null;
  try {
    const url = new URL(override.trim());
    if (url.protocol !== "https:") return null;
    if (url.hostname !== expectedHost) return null;
    if (!url.pathname.includes("/npm/@clerk/")) return null;
    return url.toString();
  } catch {
    return null;
  }
}

export function clerkJSUrlForKey(raw: string | undefined, override?: string): string | undefined {
  const host = frontendApiFromPublishableKey(raw);
  if (!host || !isAllowedClerkFrontendHost(host)) return undefined;
  return hostFromOverride(override, host) ?? scriptUrl(host, "clerk-js", CLERK_JS_MAJOR, "clerk.browser.js");
}

export function clerkUIUrlForKey(raw: string | undefined): string | undefined {
  const host = frontendApiFromPublishableKey(raw);
  if (!host || !isAllowedClerkFrontendHost(host)) return undefined;
  return scriptUrl(host, "ui", CLERK_UI_MAJOR, "ui.browser.js");
}

/** Props ClerkProvider forwards into loadClerkJSScript. `clerkJSUrl` is the public name; this SDK reads `__internal_clerkJSUrl`. */
export function clerkProviderLoadOptions(
  raw: string | undefined,
  jsOverride?: string,
): ClerkLoadOptions | Record<string, never> {
  const clerkJSUrl = clerkJSUrlForKey(raw, jsOverride);
  const clerkUIUrl = clerkUIUrlForKey(raw);
  if (!clerkJSUrl || !clerkUIUrl) return {};
  return {
    clerkJSUrl,
    __internal_clerkJSUrl: clerkJSUrl,
    __internal_clerkUIUrl: clerkUIUrl,
  };
}
