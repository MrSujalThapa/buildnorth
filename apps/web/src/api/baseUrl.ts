/** Render API host that must never be requested over HTTP from an HTTPS page. */
export const PLAYITOUT_RENDER_API_HOST = "playitout-api.onrender.com";

export type PageOrigin = Pick<Location, "protocol" | "hostname">;

function isLoopbackHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1" || hostname === "[::1]";
}

function normalizeConfigured(configured: string | undefined): string {
  return configured?.trim().replace(/^["']|["']$/g, "").replace(/\/+$/, "") ?? "";
}

/**
 * Resolve the FastAPI origin for browser fetches.
 *
 * Vite inlines `VITE_API_BASE_URL` at build time (`envDir` is the repo root, so
 * local `.env` and Vercel Production env both apply). A stale HTTP Render value
 * causes mixed-content `Failed to fetch` on the HTTPS Vercel origin.
 */
export function resolveApiBaseUrl(configured: string | undefined, page: PageOrigin): string {
  const fallback = `${page.protocol}//${page.hostname}:8000`;
  const raw = normalizeConfigured(configured);
  if (!raw) return fallback;

  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("VITE_API_BASE_URL must be an absolute URL");
  }

  const hostname = parsed.hostname.toLowerCase();
  const pageIsHttps = page.protocol === "https:";

  if (parsed.protocol === "http:" && hostname === PLAYITOUT_RENDER_API_HOST && pageIsHttps) {
    parsed.protocol = "https:";
  } else if (parsed.protocol === "http:" && !isLoopbackHost(hostname) && pageIsHttps) {
    throw new Error(`Refusing insecure remote API URL ${parsed.origin} from an HTTPS page`);
  }

  return parsed.origin;
}

export function apiRequestUrl(path: string, configured: string | undefined, page: PageOrigin): string {
  return `${resolveApiBaseUrl(configured, page)}${path}`;
}
