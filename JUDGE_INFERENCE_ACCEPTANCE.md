# Judge inference acceptance — 2026-10-19

**Status: BLOCKED for invited beta.** The deployed code and nonsecret Render limits are in place. No platform OpenAI key or BYOK encryption key ring was present in Render's environment variable list when inspected, and no authorized second judge account or provider credential was available for a live inference call. A real administrator redeemed one private entitlement and received $5. No paid inference was initiated; incremental cost is **$0.00**. Mocked tests below are not live inference evidence.

## Changes and contracts

- `867412f`: $5 user and $100 global cumulative hosted defaults, raised legacy daily guards so they do not undercut the global event cap, Render Blueprint and example configuration, atomic encrypted credential save plus BYOK activation, and clearer Settings credit/mode/provider display.
- `f1f35f4`: an unentitled administrator opening a private invitation can redeem it through the ordinary invite endpoint; this consumes a redemption and grants the normal persisted entitlement. No admin exemption was added to hosted budget checks.
- `34697e8`: Settings distinguishes a configured hosted provider from remaining credit. A missing platform key is shown as a blocker even when the global balance is $100.
- Public behavior changed: `PUT /api/v1/settings/inference/credentials/{provider}` validates, encrypts, stores, **and activates BYOK**. Its response remains masked credential metadata. `GET /api/v1/settings/inference` then reports `preference.mode=byok` and includes `hosted_configured: boolean`. Deleting a key retains BYOK mode; switching to hosted remains explicit.
- `GET /api/v1/me` continues to report per-user quota, spent/reserved/remaining dollars and tokens, global remaining dollars, and kill switch state. `POST /api/v1/admin/hosted-inference` remains the admin kill switch.

The existing `InferenceRouter`, `InferenceBudgetService`, `InferenceSettingsService`, `CredentialCipher`, `hosted_entitlements`, `hosted_budget_counters`, `inference_reservations`, and `inference_ledger` were reused. Postgres reservation updates lock through one transaction/advisory lock; settlement and ledger insertion are transactional. BYOK calls use a separate ledger mode and never reserve hosted dollars. AES-GCM credentials are owner-bound and responses include only a masked suffix. No migration or forecast model changed.

## Deployed configuration

Vercel frontend: <https://buildnorth-delta.vercel.app>. Render API: <https://playitout-api.onrender.com>. Render service `srv-dbb5k2rl550s73cf3vlg`. Vercel marked `34697e8` Ready and Render marked the same revision Live. In the actual signed-in Chrome browser, final Settings displayed OpenAI / `gpt-5.4-mini`, $5.00 / $5.00 user credit, $100.00 global balance, and **Hosted provider not configured**. An administrator redeemed a one-hour, single-redemption private invitation; invitation history showed 1 / 1 Filled. The $5 balance and Filled status remained after full browser refresh. Render access logs recorded `POST /api/v1/invites/redeem` **200** at 7:10:47 PM EDT and `/api/v1/me` **200** before and after refresh. The private URL and token were not included in this report or screenshots. A transient session `Failed to fetch` on the invitation URL resolved with the visible Try again control; the redemption succeeded afterward.

Render's nonsecret variables were set through its dashboard and triggered a rebuild: `PM_HOSTED_USER_QUOTA_USD=5`, `PM_HOSTED_GLOBAL_QUOTA_USD=100`, `PM_HOSTED_USER_QUOTA_TOKENS=5000000`, `PM_HOSTED_GLOBAL_QUOTA_TOKENS=100000000`, `PM_HOSTED_INFERENCE_ENABLED=true`, `PM_INFERENCE_PROVIDER=openai`, `PM_INFERENCE_MODEL=gpt-5.4-mini`, `PM_OPENAI_MAX_COST_USD=100`, and `PM_BYOK_ACTIVE_KEY_ID=v1`. These are cumulative event caps in persistent Postgres counters; `PM_OPENAI_MAX_COST_USD` is a separate daily guard. The deployed revision also defaults each daily token pool to 100 million. Render's environment list had **no** `PM_OPENAI_API_KEY` or `PM_BYOK_ENCRYPTION_KEYS` entry. The platform credential must be configured only in Render, never Vercel or the repository.

One-time owner setup in Render Environment:

1. Obtain an OpenAI API key authorized for this project and add `PM_OPENAI_API_KEY` as a secret. Set provider-side budget alerts/limits appropriate to a $100 application budget. Check actual model access and pricing before any paid call.
2. Generate a fresh 32-byte AES key locally with a trusted password manager or this one-time Python command in a private terminal: `python -c "import base64,secrets,json; print(json.dumps({'v1':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}))"`. Copy the resulting JSON into Render's **secret** `PM_BYOK_ENCRYPTION_KEYS`. Keep the actual value out of chat, Git, Vercel frontend configuration, screenshots, and logs. Save an encrypted backup of the key ring; losing it makes stored BYOK keys undecryptable. Preserve old key IDs when rotating. `PM_BYOK_ACTIVE_KEY_ID=v1` is already set.
3. Save and redeploy Render, confirm its revision is Live, then check the real Settings page. Do not paste either secret into this report.

## Acceptance matrix

| Workflow | Status | Evidence and limit |
|---|---|---|
| New invitation grants $5 | PASS for admin; BLOCKED for judge | The real one-time admin invitation granted $5 and became 1 / 1 Filled. No separate judge account was available. |
| Two judges, independent $5 | BLOCKED live | In-memory budget test accepts $4.99 for one, rejects another $0.02, and independently accepts $5 for a second. No two live identities. |
| Shared $100 cap and concurrency | BLOCKED live | Parallel in-memory reservations admitted 20 of 21 distinct $5 judges and left exactly $100 reserved. Existing Postgres store uses transactional user/global counter updates. No production concurrent spend was induced. |
| Cumulative persistence after refresh/restart | PARTIAL | The live $5 entitlement and 1 / 1 Filled invitation persisted after browser refresh and the later Render `34697e8` deployment; `/me` returned 200. Direct production SQL and nonzero usage ledger rows were unavailable. |
| Hosted inference after redemption | BLOCKED | With real $5 entitlement, submitting a synthetic goal in the live browser returned `API request failed (Selected hosted provider is not configured)`. Render logged `POST /api/v1/agent/threads` **503** at 7:12:29 PM EDT. Returning to Settings showed $5.00 / $5.00, so the rejected call did not debit hosted credit. No model response or provider charge. |
| OpenAI BYOK connection and activation | BLOCKED live | Local API test validates/stores encrypted mock key and immediately reports BYOK. Real key absent. |
| Anthropic BYOK connection and activation | BLOCKED live | Same local boundary/owner tests pass; real key absent. |
| BYOK usage does not debit hosted | BLOCKED live | Local API test preserves `/me.hosted` across connection, and router tests separate BYOK accounting. No paid BYOK generation. |
| Hosted/BYOK switching and key deletion | BLOCKED live | Local API test switches back to hosted and deletion keeps BYOK selected. No live valid key. |
| Settings UX and refresh | PASS live for read-only controls; BLOCKED for connection | Vercel revision `34697e8` Ready; Render revision Live. Live Chrome displayed Hosted, OpenAI, `gpt-5.4-mini`, $5 user, $100 global, and the missing-provider blocker after refresh. Local desktop/mobile browser paths cover activation; real connection untested. |
| Admin hosted test entitlement | PASS live | `f1f35f4` exposed ordinary invite redemption to an unentitled administrator. A real single-use invitation granted $5 and became 1 / 1 Filled. |
| Unauthorized/uninvited and secret handling | PASS local; BLOCKED full live | Existing auth and owner-scope tests pass; Pass 06 live unauthorized probes returned 401. No new credential was entered live; production encryption and cross-user behavior remain unverified. |
| Kill switch | PASS local; BLOCKED live | Existing budget test blocks hosted reservations when disabled. Do not toggle production while users may be active. |

Pre-existing invitations retain their immutable recorded allowance. The older $2 invitations should be identified by the administrator's invitation history and replaced with new $5 links if still unredeemed. Redeeming another invitation does not top up an already enabled entitlement; user and global spent counters remain unchanged. Do not rewrite a redeemed entitlement or reset counters to make a test pass.

## Verification and remaining exposure

Backend: 73 targeted tests passed, including invitation, inference routing, budget and BYOK API cases. Frontend: 63 unit tests, typecheck, production build, lint with zero errors and ten existing warnings. Eight fixture-backed Playwright paths passed in desktop Chrome and 390px mobile Chromium. Ruff check and formatting of changed Python files passed. No actual provider calls were made, so provider billing totals and model responses remain unverified.

Application dollar limits use model-price estimates and bound output tokens before each request. Actual input/output usage and retries can exceed a reservation estimate; settlement records the estimated actual usage afterward, so these are **not upstream hard billing caps**. Provider-side alerts or spend controls are required. The $100 application limit is cumulative in Postgres and does not reset daily; the separate daily guard can restrict usage independently. Direct Supabase verification, real OpenAI/Anthropic key validation, actual judge redemption, and post-deployment mode switching remain blockers. External invited beta is not ready.
