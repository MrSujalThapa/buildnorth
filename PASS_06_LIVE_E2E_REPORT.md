# Pass 06 — Live Production End-to-End Verification

Date: 2026-10-19 (America/Toronto, EDT).
Frontend: https://buildnorth-delta.vercel.app
Backend: https://playitout-api.onrender.com
Branch: main. Starting revision: 2963d37.

**Acceptance decision: NOT READY for external invited beta testers.** The live browser goal workflow returns HTTP 503 because hosted inference is not configured. Goal persistence, baseline forecasting, What If and interventions cannot be accepted without completing that workflow. No successful AI inference is claimed.

## Evidence and status rules

- PASS: the named behavior was observed with the stated evidence and scope.
- FAIL: an attempted behavior produced an incorrect result, or a known defect remains.
- BLOCKED: a necessary provider, identity, credential or tool capability was unavailable.
- NOT TESTED: no execution of that behavior occurred. Source review and local tests are not live passes.
- Live product testing used the existing signed-in Chrome session and the deployed URLs. No mocks, synthetic login tokens, test-auth bypass or local server were used for live browser acceptance.
- Local Vitest/Playwright/backend regressions are reported separately. Their fixtures are not evidence of live AI, data isolation or successful forecasting.
- Browser console was inspected. The automation exposes console logs but no Network request/response inspector. Actual HTTP statuses were correlated with Render application access logs viewed in the browser. Raw authenticated `/me` response JSON was not exported; the Settings role rendered from `/me` and its HTTP 200 access-log entry corroborate administrator access.
- No authentication token, cookie, API key or live invitation URL is included in this report. Render log excerpts were reduced to methods, paths, statuses and timestamps.

## Verification matrix

| Workflow | Status | Evidence | Issues |
| --- | --- | --- | --- |
| Admin Google login — existing session | PASS | Existing Chrome account opened Settings and Markets; Settings shows Administrator / verified email; Render records GET /api/v1/me 200. | Fresh Google OAuth login was not repeated. Clerk development-key warning remains. |
| Fresh Google OAuth login | NOT TESTED | Existing administrator session was reusable. | No need to sign out the working administrator. |
| Administrator API role | PASS | Settings renders the role from /me; authenticated admin invitation listing/creation/revocation succeeds. | Raw authenticated /me JSON was not separately captured. |
| Signed-out browser gate | PASS | Separate in-app browser at /markets displays Sign in / Continue with Google, without markets. | Does not prove signed-in non-invited enforcement. |
| Navigation and refresh continuity | PASS | Markets, Settings, Plugins, Social and /new exercised; /markets and /new survive full refresh after fix; account stays signed in. | Goal-detail refresh blocked by lack of a created goal. |
| Goal creation | BLOCKED | Create goal → /new → submitted labelled PASS06 synthetic running goal → Workflow unavailable: Hosted inference is not configured. Render POST /api/v1/agent/threads 503 at 17:01:01 EDT. | Provider configuration, not a successful model call. Entry-point and error-display defects fixed. |
| Goal persistence | BLOCKED | No goal committed by the failed creation flow; Markets remains empty. | A persisted goal cannot be checked without successful creation. |
| Baseline forecast | BLOCKED | No owner goal exists after the browser attempt. | Cannot inspect numerical result, receipt, lineage or DB forecast. |
| What If | BLOCKED | No owner goal/baseline available. | No simulation numerical-update acceptance claimed. |
| Intervention | BLOCKED | No owner goal/baseline available. | Neither semantic parsing nor numerical impact verified live. |
| Forecast history / persistence | BLOCKED | No forecast or scenario was generated. | Refresh of forecast/history and API/DB numeric reconciliation not possible. |
| Editing goals | NOT TESTED | No created goal. Source review finds only GET list/get in goals API and no edit workflow. | Feature gap; not implemented as part of an E2E repair. |
| Settings appearance and preference persistence | PASS | Changed Dark → Light, saved existing hosted preference, refreshed; Light and hosted mode retained. | Theme is browser preference; hosted preference is server-backed. |
| Dashboard statistics | BLOCKED | Empty state shows No goals yet without invented odds. | No real goal/statistic to reconcile. |
| Social numerical honesty | PASS | Deployed page now says No shared goals / Social sharing is not available yet. | Sharing itself remains unavailable. Hardcoded names/+pts removed. |
| Plugins navigation | PASS | Production page loads Installed 0; Manual and CSV Import are listed. | External connector OAuth/sync not exercised. |
| ChatGPT / OpenAI model inference | BLOCKED | Settings reports hosted provider none; OpenAI has no stored key; real goal request fails closed with 503. | No real output, model run ID, billable usage or positive connectivity result. |
| ChatGPT remote MCP connector | NOT TESTED | Settings exposes public MCP endpoint and no connected agents. | No hosted ChatGPT connector consent/round-trip performed. |
| Grok | NOT TESTED | Settings explicitly labels Grok client integration untested; no connected agents. Native BYOK only offers OpenAI/Anthropic. | No configured Grok client or inference adapter exercised. |
| BYOK positive path | BLOCKED | No saved OpenAI credential; no usable key supplied through Settings. | Encryption-at-rest, masking of a real stored key, validation/deletion and successful model invocation unverified live. |
| BYOK missing-key guard | PASS | Selecting BYOK then saving returns Add and validate a key before selecting BYOK. Render PUT /api/v1/settings/inference 503 at 16:57:32 EDT; restoring hosted returns 200 at 16:59:14 EDT. | Positive connectivity remains blocked. |
| Quota display / zero-call accounting | PASS | Hosted $0/$0, 0 tokens; BYOK 0 calls/0 tokens/$0.0000 before and after rejected workflows. | No paid debit, reservation reconciliation or exhaustion path exercised live. |
| Quota debit / exhaustion | NOT TESTED | No paid provider call initiated. | Passing local budget tests is not live billing acceptance. |
| Invitations — full creation/redemption | BLOCKED | Bounded creation/revocation/history checked separately below. | No authorized second Google test account available for redemption, duplicate/cap/expiry behavior. |
| Invitation creation / revocation / history | PASS | Private test invitation limited to one redemption, one hour; API creation 200, row persisted after reload, then Revoked with 0/1 redeemed. | Initial clipboard-dependent UI defect repaired; post-fix live rerun recorded below. No links distributed. |
| Multi-user isolation | BLOCKED | No authorized second signed-in account. | Local owner-isolation regression is not live two-user evidence. |
| Invite-only signed-in nonmember enforcement | BLOCKED | No nonmember Google test account. | Anonymous API protection and signed-out UI pass separately. |
| Anonymous / invalid bearer / spoofed owner protection | PASS | /me, /goals, /admin/invites, /settings/inference return 401 without bearer; malformed bearer and X-User-ID spoof rejected. /mcp without auth returns 401. | Limited probes do not prove absence of every possible bypass. |
| Untrusted-origin CORS | PASS | OPTIONS /api/v1/me from a synthetic untrusted origin returns 400 Disallowed CORS origin, no allow-origin response. | Does not replace bearer authorization. |
| Public detailed health protection | PASS | GET /health/details returns 404 to remote caller; /health returns minimal 200 response. | No detailed database/secret configuration exposed in response. |
| Real session expiry | NOT TESTED | Existing session continuously usable; no session revoked or allowed to expire. | Synthetic expired-token checks are separate below. |
| Forged expired / malformed signing header | PASS | Same unsigned expired admin-claim JWT that originally returned 500 now returns 401 / invalid token after Render deployed 9a5eb1d. | This is a synthetic invalid-token probe, not expiry of a real Clerk session. |
| Live mobile product verification | BLOCKED | Chrome viewport override attempts returned without changing observed DOM width (1440px). | Real local Chromium mobile regressions at 390px passed; no live-mobile product pass claimed. |

## Defects and fixes

| Defect / exact action | Observed result | Cause / owner | Repair |
| --- | --- | --- | --- |
| Open empty /markets and try to create a goal | No creation control; no HTTP request possible | Frontend MarketsPage | Create goal link to existing /new route; empty-state spacing. |
| Directly load /new as uninvited administrator | Client-side redirect to /settings, losing requested page | Frontend AuthGate | Restrict admin landing redirect to / and /invite; preserve explicit routes. |
| Open goal composer / trigger provider failure | Browser-default form styling; generic error hides server reason | Frontend NewGoalPage / missing stylesheet | Scoped responsive styles, actual safe API error, recovery link to Settings. |
| Generate bounded invitation at /settings | POST /api/v1/admin/invites 200 at 17:01:44 EDT, UI remains Generating | Frontend awaited clipboard permission before refreshing history | Make copy explicit and independent of creation; handle copy rejection. |
| Click Revoke at narrow width in regression | Pointer interception / overflow prevents click | Frontend invitation flex layout | Constrain URL flex child; stack row/actions on narrow screens. |
| Visit /social | Hardcoded people and +3.4/+5.1/+2.2 pts presented as user data | Frontend static demo content | Remove fabricated movements; honest unavailable state. |
| GET /api/v1/me with unsigned expired forged admin JWT (alg:none, no kid) | HTTP 500 Internal Server Error; no access granted | Backend identity/tokens.py; Render log: PyJWKClientError: Unable to find a signing key that matches None | Reject malformed signing headers before key lookup; map typed JWKS lookup failures to UnauthorizedError / 401. |
| Submit live goal | HTTP 503 Hosted inference is not configured | Render/application provider configuration; Settings hosted_provider none | Operator configuration required; no secret, quota or infrastructure change attempted. |

Clerk console also reports development keys on a deployed application. This is an operator readiness issue; no production Clerk migration or security setting was changed. Render startup identifies Supabase PostgreSQL and environment staging. Render warns that its free instance may sleep; the application logs require a single worker because some MCP locks/rate counters are process-local.

## Commits and verification

- `ad240988ac5b052ec7754f4dee11aae2d180a3af` — goal entry, admin deep links, composer styling and actionable failure. Pushed to main. Vercel deployment Fn6dKSL5Ry7fDEqFUCmbMVJjsy34 was Ready with the production domain; browser confirmed repairs.
- `9d3fc79` — clipboard-independent invitations, narrow invitation layout, honest Social state; pushed to main. Live Social empty state observed.
- `9a5eb1d` — reject malformed Clerk signing headers and catch JWKS key-lookup failures; pushed to main. Deployed security recheck recorded below.

### Final deployed recheck

- Render marked `9a5eb1d37a3f5ffbe1b7141be8e032b7c45c7529` Live in deployment `dep-dbb8dripp74s73bmvbug` (2m14s deploy). A probe made during the old-instance overlap still returned 500 at 17:11:29 EDT; the same probe after the new instance became live returned **401** at **17:11:48 EDT**, with JSON `UnauthorizedError / invalid token`. Both observations are retained; the final result is corroborated by the new-instance Render log and `.artifacts/pass06/jwt-post-fix.json`.
- The post-fix invitation POST returned **200 at 17:10:02 EDT**. The UI completed generation without clipboard access and exposed Revoke. Revocation POST returned **200 at 17:11:15 EDT**; GET history returned **200**. After full reload, both PASS06 test invitations show **Revoked, 0/1 redeemed**; neither URL was distributed. The active-link screenshot was deliberately not saved.
- The administrator remained signed in after deployed changes and repeated refreshes. Hosted inference still reports none, no OpenAI key, $0 hosted allowance and zero BYOK usage. Original Dark appearance was restored after verifying Light persistence.
- Deployed Social shows the honest unavailable state. The separate signed-out browser shows the Google sign-in gate.

Executed local checks:

| Check | Result | Scope |
| --- | --- | --- |
| npm run test --workspace @personal-markets/web | 61 passed / 17 files | Includes admin deep-link/refresh, creation navigation, provider failure, pending clipboard/revocation, no fake Social movements. |
| npm run test:e2e --workspace @personal-markets/web -- e2e/pass06_navigation.spec.ts | 4 passed | Real Chromium desktop/mobile, local fixture-backed regression only; no live provider claim. |
| npm run build | PASS | TypeScript + Vite production bundle. Existing >500 kB chunk warning. |
| npm run typecheck --workspace @personal-markets/web | PASS | Final TypeScript check. |
| npm run lint --workspace @personal-markets/web | PASS | 0 errors, 10 pre-existing warnings. |
| uv run python -m pytest apps/api/tests/test_clerk_jwt.py apps/api/tests/test_phase1_auth.py apps/api/tests/test_phase1_budget.py apps/api/tests/test_phase2_inference.py apps/api/tests/test_inference_provider_selection.py | 79 passed | Local signed-RSA Clerk validation, identity, isolation, quota and inference routing; 5 new malformed/unknown signing-key HTTP regressions. |
| uv run ruff check apps/api/src/personal_markets/identity/tokens.py apps/api/tests/test_clerk_jwt.py | PASS | Changed Python files. |
| npm run check:architecture / npm run check:migrations | PASS | Dependency invariants; 15 migration files / 16 required tables. No migration executed against production. |
| git diff --check | PASS | Changed files. |

Failed attempts retained: first unit parameterization spread the goal array (corrected); first lint found require-await in a test stub (corrected); fixture typing/ambiguous selectors corrected; first mobile invitation path exposed real layout obstruction (repaired, rerun passed). Bare uv run pytest selected an unsuitable entry point; uv run python -m pytest passed. No unrelated refactor or benchmark rerun.

## Persistence, numerical reconciliation and performance limits

Invitation history and hosted preference survive actual page reloads; Render startup confirms Supabase as the deployed database. No direct production SQL credentials/session were used. Local database configuration points to loopback and was explicitly excluded as production evidence. No direct Supabase row query, goal/forecast-row verification or numerical API/UI/DB reconciliation was possible for the blocked product chain.

No forecasting math, final-probability contract, model parameters, quotas or database schemas changed. Frontend fixes add no API round trip to the forecast path; invitation creation no longer waits on clipboard permission. Final local bundle was approximately 920.37 kB JS (265.55 kB gzip) / 68.25 kB CSS (13.19 kB gzip); no optimization claim. Authenticated API p50/p95, DB query counts, simulation runtime and live render performance were not benchmarked. Public unauthenticated probe durations are recorded in the local JSON and are not authenticated performance measurements.

## Evidence files

Screenshots and sanitized diagnostics remain local under `.artifacts/pass06/` (intentionally ignored by Git):

- `markets-fixed-desktop.jpg` — deployed creation entry and empty state.
- `goal-create-live-result.jpg` — real submitted goal and unconfigured-provider failure.
- `byok-missing-key.jpg` — live missing-key rejection and zero usage.
- `invitation-revoked-first.jpg` — revoked bounded invitation, zero redemptions.
- `invitation-revoked-final.jpg` — both private invitations revoked and persisted after refresh.
- `social-live-honest-state.jpg` — deployed removal of fabricated movements.
- `guest-sign-in.jpg` — separate signed-out browser gate.
- `render-requests.txt` — sanitized request-status excerpts, refreshed at final verification.
- `public-api-checks.json` — supplemental real unauthenticated security probes, before final JWT repair.
- `jwt-post-fix.json` — final live 401 result for the previously failing forged-token case.

Local regression screenshots are under `apps/web/test-results/`; they must not be presented as live production screenshots. The file previously named `goal-create-live-320.jpg` retained a 1440px viewport and is explicitly excluded from mobile evidence.

`docs/IMPROVEMENT_CHANGELOG.md` received append-only entries for each experiment/failure/repair. The repository intentionally ignores `/docs/`, so existing private historical documentation was not force-added to Git. This root report and code/tests are committed.

## Cost and beta readiness

Paid inference initiated by this pass: **$0.00**, below the authorized $0.10 limit. No paid model response was produced. BYOK counters remained zero. Displayed quotas were checked before the real goal attempt; missing provider fails before dispatch. No keys, test-auth bypasses or enlarged allowances were installed to force the workflow through.

Required next steps: configure an approved live provider and usable administrator allowance/BYOK within the $0.10 test ceiling; rerun goal → baseline → What If → intervention → history with real persisted numerical results; provide an authorized second Google account for invitation redemption/isolation/nonmember checks; validate a real stored BYOK key and paid quota accounting; resolve Clerk deployment configuration; complete live mobile and session-expiry checks. ChatGPT/Grok hosted-client OAuth round-trips remain unverified. Goal editing and Social sharing remain feature gaps.

**Pass 06 is incomplete / blocked.** Session, navigation, preferences, bounded invitation lifecycle, failure handling and limited anonymous security checks were verified live. The core successful forecast journey and live AI integrations were not.
