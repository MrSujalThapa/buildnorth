import { expect, test } from "vitest";
import {
  clerkJSUrlForKey,
  clerkProviderLoadOptions,
  frontendApiFromPublishableKey,
  isAllowedClerkFrontendHost,
  normalizePublishableKey,
} from "./clerkScript";

function publishableKey(host: string, kind: "test" | "live" = "test"): string {
  const encoded = btoa(`${host}$`).replace(/=+$/, "");
  return `pk_${kind}_${encoded}`;
}

const DEV_HOST = "foo-bar-13.clerk.accounts.dev";

test("normalizes quoted keys and a duplicated pk prefix", () => {
  const valid = publishableKey(DEV_HOST);
  expect(normalizePublishableKey(`  "${valid}"  `)).toBe(valid);
  expect(normalizePublishableKey(`p${valid}`)).toBe(valid);
  expect(frontendApiFromPublishableKey(`p${valid}`)).toBe(DEV_HOST);
});

test("builds the ClerkJS URL on the instance frontend API host", () => {
  const key = publishableKey(DEV_HOST);
  expect(clerkJSUrlForKey(key)).toBe(
    `https://${DEV_HOST}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`,
  );
  const options = clerkProviderLoadOptions(key);
  expect(options.clerkJSUrl).toBe(clerkJSUrlForKey(key));
  expect(options.__internal_clerkJSUrl).toBe(clerkJSUrlForKey(key));
  expect(options.__internal_clerkUIUrl).toBe(`https://${DEV_HOST}/npm/@clerk/ui@1/dist/ui.browser.js`);
});

test("rejects open redirects and empty hosts", () => {
  expect(clerkJSUrlForKey(undefined)).toBeUndefined();
  expect(clerkJSUrlForKey("pk_test_????")).toBeUndefined();
  expect(isAllowedClerkFrontendHost("evil.example")).toBe(false);
  expect(clerkJSUrlForKey(publishableKey(DEV_HOST), "javascript:alert(1)")).toBe(
    `https://${DEV_HOST}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`,
  );
  expect(clerkJSUrlForKey(publishableKey(DEV_HOST), `https://evil.example/npm/@clerk/clerk-js@6/dist/clerk.browser.js`)).toBe(
    `https://${DEV_HOST}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`,
  );
});

test("accepts an override only on the same Clerk host", () => {
  const key = publishableKey(DEV_HOST);
  const override = `https://${DEV_HOST}/npm/@clerk/clerk-js@6.39.0/dist/clerk.browser.js`;
  expect(clerkJSUrlForKey(key, override)).toBe(override);
});
