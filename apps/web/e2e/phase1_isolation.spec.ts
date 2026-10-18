import { expect, test } from "@playwright/test";

const apiBase = process.env.PHASE1_API_BASE_URL || process.env.VITE_API_BASE_URL || "http://127.0.0.1:8010";
const secret = process.env.PM_TEST_AUTH_SECRET || "phase1-test-secret-must-be-32b!!";

async function issueToken(clerkUserId: string, email: string): Promise<string> {
  const { createHmac } = await import("node:crypto");
  const header = Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url");
  const now = Math.floor(Date.now() / 1000);
  const payload = Buffer.from(
    JSON.stringify({
      sub: clerkUserId,
      email,
      email_verified: true,
      iss: "playitout-test",
      iat: now,
      exp: now + 3600,
    }),
  ).toString("base64url");
  const data = `${header}.${payload}`;
  const signature = createHmac("sha256", secret).update(data).digest("base64url");
  return `${data}.${signature}`;
}

test("two authenticated identities cannot see each other's goals", async ({ browser }) => {
  const health = await fetch(`${apiBase}/health`);
  test.skip(!health.ok, "API is not running on :8000");

  const tokenA = await issueToken("browser-user-a", "a@example.test");
  const tokenB = await issueToken("browser-user-b", "b@example.test");
  const meA = await fetch(`${apiBase}/api/v1/me`, { headers: { Authorization: `Bearer ${tokenA}` } });
  const meB = await fetch(`${apiBase}/api/v1/me`, { headers: { Authorization: `Bearer ${tokenB}` } });
  test.skip(meA.status === 401, "API is not accepting test tokens");

  const accountA = await meA.json();
  const accountB = await meB.json();
  if (!accountA.invited || !accountB.invited) {
    test.skip(true, "Test users are not invited; enable PM_DEV_BOOTSTRAP_TEST_USERS for local browser isolation");
  }

  const created = await fetch(`${apiBase}/api/v1/agent/threads`, {
    method: "POST",
    headers: { Authorization: `Bearer ${tokenA}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      kind: "create_goal",
      intent: "I want to receive an SWE offer from a target company by August 2027.",
    }),
  });
  expect(created.status).toBe(200);
  const thread = await created.json();
  const resumed = await fetch(`${apiBase}/api/v1/agent/threads/${thread.thread_id}/resume`, {
    method: "POST",
    headers: { Authorization: `Bearer ${tokenA}`, "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed: true }),
  });
  expect(resumed.status).toBe(200);
  const goalId = (await resumed.json()).goal.goal_id as string;

  const mine = await fetch(`${apiBase}/api/v1/goals/${goalId}`, {
    headers: { Authorization: `Bearer ${tokenA}` },
  });
  const stolen = await fetch(`${apiBase}/api/v1/goals/${goalId}`, {
    headers: { Authorization: `Bearer ${tokenB}` },
  });
  expect(mine.status).toBe(200);
  expect(stolen.status).toBe(404);

  const contextA = await browser.newContext();
  const contextB = await browser.newContext();
  const owned = await contextA.request.get(`${apiBase}/api/v1/goals/${goalId}`, {
    headers: { Authorization: `Bearer ${tokenA}` },
  });
  const stolenBrowser = await contextB.request.get(`${apiBase}/api/v1/goals/${goalId}`, {
    headers: { Authorization: `Bearer ${tokenB}` },
  });
  expect(owned.status(), await owned.text()).toBe(200);
  expect(stolenBrowser.status()).toBe(404);
  await contextA.close();
  await contextB.close();
});
