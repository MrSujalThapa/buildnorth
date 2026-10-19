import { expect, test } from "vitest";
import { apiRequestUrl, resolveApiBaseUrl } from "./baseUrl";

const vercel = { protocol: "https:", hostname: "buildnorth-delta.vercel.app" } as const;
const local = { protocol: "http:", hostname: "127.0.0.1" } as const;
const staleHttpRender = "http://playitout-api.onrender.com";

test("HTTPS production upgrades the stale HTTP Render API origin", () => {
  expect(resolveApiBaseUrl(staleHttpRender, vercel)).toBe("https://playitout-api.onrender.com");
  expect(resolveApiBaseUrl("http://playitout-api.onrender.com/", vercel)).toBe(
    "https://playitout-api.onrender.com",
  );
  expect(resolveApiBaseUrl(`"${staleHttpRender}"`, vercel)).toBe("https://playitout-api.onrender.com");
});

test("HTTPS production never requests the HTTP Render URL", () => {
  const url = apiRequestUrl("/api/v1/me", staleHttpRender, vercel);
  expect(url).toBe("https://playitout-api.onrender.com/api/v1/me");
  expect(url.startsWith("http://playitout-api.onrender.com")).toBe(false);
  expect(url.startsWith("https://")).toBe(true);
});

test("HTTPS production keeps an already-HTTPS Render origin", () => {
  expect(resolveApiBaseUrl("https://playitout-api.onrender.com", vercel)).toBe(
    "https://playitout-api.onrender.com",
  );
});

test("localhost HTTP development is preserved", () => {
  expect(resolveApiBaseUrl(undefined, local)).toBe("http://127.0.0.1:8000");
  expect(resolveApiBaseUrl("http://127.0.0.1:8000", local)).toBe("http://127.0.0.1:8000");
  expect(resolveApiBaseUrl("http://localhost:8000", { protocol: "http:", hostname: "localhost" })).toBe(
    "http://localhost:8000",
  );
});

test("HTTPS pages reject unexpected insecure remote APIs", () => {
  expect(() => resolveApiBaseUrl("http://evil.example", vercel)).toThrow(/Refusing insecure remote API URL/);
  expect(() => apiRequestUrl("/api/v1/me", "http://other-service.onrender.com", vercel)).toThrow(
    /Refusing insecure remote API URL/,
  );
});
