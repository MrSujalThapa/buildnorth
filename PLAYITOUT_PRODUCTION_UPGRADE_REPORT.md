# PlayItOut production upgrade report

Date: 2026-10-19  
Working branch: `main`  
Live frontend: https://buildnorth-delta.vercel.app  
Live API: https://playitout-api.onrender.com  

This report distinguishes **local mocked tests** from **real deployed browser verification**. Compiling or unit-testing is not treated as production-ready proof.

The earlier sections below record the pre-sign-in state. The dated acceptance addendum at the end supersedes their live-status and blocker statements. No additional paid inference was deliberately initiated in the remediation pass; the preexisting BYOK ledger could not be used to isolate a per-pass charge.

## 2026-10-21 consumer UI pass

Branch `ux/consumer-profile-whatif`. Cron, watch-runner, and Render scheduler were not modified.

| Surface | Status | Evidence |
| --- | --- | --- |
| Profile edit owns the photo | PASS mocked | Playwright desktop and mobile profile spec |
| Radar hides estimator text and closes only when every trait is measured | PASS | Vitest partial-polygon test; Playwright screenshot of a synthetic six-trait fixture |
| Area editor | PASS mocked | Unique title match links Reading to “Read 20 books” without a goal matrix |
| Icon rail | PARTIAL | Present in the same Playwright screenshot; hover expansion not separately asserted |
| What If four modes | PARTIAL | Reverse label, composer, and unsupported Futures short-circuit are in code. Live simulations not re-run |
| What If attachments | BLOCKED | No ingestion path added; the button was not faked |
| Speech input | PARTIAL | Browser Speech Recognition when the API exists; otherwise the mic is disabled |
| Notion titles | PARTIAL | Titles still come from the provider title property. URL and connected-account id are now kept. The unfamiliar pages were not re-fetched from the live account |
| Plugin catalog | PARTIAL | Popular list stays local; Browse all sets `browse=true` and calls Composio. Not exercised against live Composio |
| Demo forecast fixtures | NOT DONE | No synthetic history was inserted |

---

## 1. Architecture changes

Hosted inference is fail-closed on Spur. `auto` with a Spur key selects Spur; without a Spur key it selects `none`. Hosted mode does not fall back to OpenAI or Anthropic. BYOK remains a separate billing mode and does not consume the $5 / $100 hosted application counters.

Provider-backed model discovery lists IDs returned by the user's saved credentials. Unknown IDs are not invented. Structured/tool compatibility is classified separately from mere text generation. Hosted users may only use the platform allowlist (currently `spur-glm-5-3`).

Dashboard reads use `GET /api/v1/goals/dashboard` instead of N+1 history fetches. Plugin catalog reads no longer reconcile Composio on every GET; toolkit metadata is cached; Composio errors keep Manual and CSV visible. Agent `POST` with `Prefer: respond-async` persists a running thread snapshot, returns immediately, then continues on the same Render worker; the client polls `GET /api/v1/agent/threads/{id}`. Sync remains the default for existing tests and scripts.

Collections are first-class owner-scoped rows (`collections`, `collection_goals`). Aggregate collection figures are labeled **progress**, never joint probability. Goals archive via `status='archived'` rather than hard delete. Profiles are stored on `app_users` and are distinct from Clerk identity.

Withhold snapshots persist on `goals.model_requirements_json.last_publication` so refresh does not collapse to “No published odds”.

---

## 2. Phase-by-phase implementation status

| Phase | Code | Local tests | Live production |
| --- | --- | --- | --- |
| 1 Inference (Spur, BYOK, discovery) | Implemented | PASS | NOT TESTED (Clerk Google sign-in required) |
| 2 Latency (RQ, dashboard, DB pool, plugin cache, async agents) | Implemented | PASS targeted | PARTIAL — warm `/health` median **155 ms** (n=5); first-hit cold start still observed |
| 3 Composio / Plugins | Implemented catalog/error path | PASS mocked | NOT TESTED (401 without session; catalog behind auth) |
| 4 Settings privacy + Hosted/BYOK split | Implemented | PASS | Bundle live (`PlayItOut credits` in production JS); UI not exercised signed-in |
| 5 Create menu, select, archive | Implemented | PASS | Bundle live (`New collection` in production JS); UI not exercised signed-in |
| 6 Collections + progress | Implemented | PASS | Local 0016 applied. Hosted: `GET /api/v1/collections` **401** (router live). Row-level table proof needs a session |
| 7 Profile + radar | Implemented | PASS | `GET /api/v1/profile` **401**. Vercel `/profile` exists. Not exercised signed-in |
| 8 Withheld + evidence UX | Implemented | PASS classifier | NOT TESTED in deployed signed-in UI |
| 9 Deploy + this report | Report updated | Targeted suite PASS | Vercel **0e2eaef** Ready. Render `/health` 200 JSON. GitHub CI still fails on pre-existing ruff |

---

## 3. Bugs discovered and root causes

1. **Empty Plugins catalog.** Composio off or one-page remote search plus frontend `isFetching` blanking made the page look empty. Local Manual/CSV were dropped on provider errors. Fix: keep local integrations, surface `provider_status`, cache toolkits, search in memory, stale-while-revalidate catalog.
2. **Markets N+1.** Goal list plus per-goal history. Fix: batched dashboard payload.
3. **Global $100 leaked on `/me`.** Backend now omits `global_remaining_usd` unless `role==admin`.
4. **Hosted `auto` could imply OpenAI.** Fail-closed: Spur or none.
5. **Withheld odds vanished after refresh.** Critic decision lived only in navigation state. Fix: persist `last_publication`.
6. **No goal deletion.** Soft-archive using existing `status`.
7. **Username in sidebar opened Settings.** Now `/profile`.
8. **Collection service in tests used a new in-memory repo per request.** Shared repository in `isolated_app`.
9. **Render cold start.** Unauthenticated `/health` returned the Render “Application loading” interstitial rather than JSON. This is a primary live latency source, separate from app code. After wake, five probes: 335 / 214 / 155 / 128 / 146 ms (median 155 ms).
10. **Vercel `tsc -b` vs local `tsc --noEmit`.** Markets `mutateAsync` returned `CollectionView` where the page typed `Promise<void>`. Local typecheck passed; Vercel `npm run build` (`tsc -b && vite build`) failed until `0e2eaef`.
11. **GitHub CI lint.** After Profile ESLint was fixed, `uv run ruff check .` still reports hundreds of pre-existing E501/I001 findings. Not introduced by this upgrade; not mass-rewritten.

---

## 4. Commit SHAs

- Previous `HEAD`: `386dfc4`
- `a36af19` — *Ship judge-facing product upgrades without inventing odds or hosted OpenAI fallback.*
- `e3ebeaa` — *Record the upgrade commit SHA in the production report.*
- `9ffa538` — *Refuse silent local Postgres when migrating PlayItOut schema.* Pushed to `origin/main`.
- `192ffaa` — *Return agent workflows without blocking the HTTP request.*
- `0e2eaef` — *Fix the Vercel production build for the Markets create flow.* **Vercel Ready** (`FvgiDWbZY2km65zvFBxNNeotce4T`). Live bundle `index-0jpWn8rs.js` contains `PlayItOut credits`, `New collection`, and `Prefer: respond-async`.

---

## 5. Database migrations

Additive migration:

- `supabase/migrations/0016_collections_profiles.sql`
  - `app_users.display_name`, `username`, `bio`, `avatar_value`
  - unique `lower(username)`
  - `collections` and `collection_goals`

Target is the hosted Supabase project behind Render `PM_DATABASE_URL`, not the local CLI database on port 54322. Inspect `schema_migrations` before applying; skip files already recorded.

Local dry-run (development, loopback `127.0.0.1:54322/postgres`): **0016 applied**, `pending (none)`, `collections_table True`. Local `.env` is intentionally not production.

Hosted: do **not** apply from this machine. Render start command runs `scripts/db_migrate.py` against the service `PM_DATABASE_URL`. After the pushed SHA boots, verify collections/profile via the authenticated API. Previously connected Supabase MCP is not authoritative.

No destructive SQL. Hosted budgets were not reset. No second database was created. `supabase db push` was not used.

---

## 6. API contract changes

Additive unless noted:

- `GET /api/v1/goals/dashboard` now also returns `collections`
- `DELETE /api/v1/goals/{id}` archives (owner only)
- `POST /api/v1/goals/archive`
- `POST /api/v1/goals/{id}/restore`
- `GET/POST /api/v1/collections`, `GET/PATCH/DELETE /api/v1/collections/{id}`, `POST .../goals`
- `GET/PATCH /api/v1/profile`
- `GET /api/v1/me` includes `profile` and `hosted.hosted_available`; `global_remaining_usd` is null for non-admins
- `GET /api/v1/settings/inference/models` (from earlier phase work)
- Goal `model_requirements.last_publication` for withheld/published snapshots
- `Prefer: respond-async` on agent start/resume/evidence returns a running snapshot; poll `GET /api/v1/agent/threads/{id}` (default remains synchronous)

---

## 7. Screenshots / real UI tests

- Local Vitest: `apps/web/src/App.test.tsx` plus InferenceSettings and NewGoalPage — PASS.
- Playwright pass06 mocks updated for the Create split control. Fixture-backed only.
- Live Vercel `0e2eaef` Sign in page loaded (Google OAuth). Production JS includes Hosted/BYOK copy and the create-menu strings.
- Signed-in Markets / Settings / Plugins / Profile / inference: **NOT TESTED** (Clerk Google).

---

## 8. Performance benchmarks

### Before (observed)

| Item | Evidence | Notes |
| --- | --- | --- |
| Render `/health` | Cold-start HTML interstitial, 20s+ in this probe | Not application JSON latency |
| Markets | N+1 `GET /goals` + history per goal | Code inspection + prior live complaint |
| Plugins | Full catalog refetch; `isFetching` blanked UI | Code inspection |
| Agent threads | Synchronous inference before response | Code inspection |

Median/p95 of warm authenticated page navigations were **not** collected with a large sample. Do not treat the cold-start interstitial as p50 of a warm instance.

### After (local / code)

| Change | Expected effect | Live after deploy |
| --- | --- | --- |
| Dashboard batch | One round-trip for markets | Route live (`GET /api/v1/goals/dashboard` 401 unauthenticated) |
| React Query 60s stale, no refetchOnWindowFocus | Cached navigations | NOT TESTED |
| Plugin debounce 280ms + toolkit cache | Fewer Composio calls | NOT TESTED |
| Engine LRU + pool | Less connection churn | NOT TESTED |
| Async agent jobs | `Prefer: respond-async` seeds a running snapshot then continues after the HTTP response; client polls `GET /api/v1/agent/threads/{id}` | Local PASS; live NOT TESTED |

Target of sub-second warm cached navigation is **not claimed** until a post-deploy waterfall is captured.

---

## 9. Real Spur / Anthropic inference

| Check | Result |
| --- | --- |
| Code path hosted provider Spur | PASS (unit: `auto` never falls back to OpenAI) |
| Live Spur completion | NOT TESTED ($0.00 spent) |
| Live Anthropic BYOK completion | NOT TESTED this session; prior owner inspection had successful **key validation** only |
| Live OpenAI BYOK | NOT TESTED |

---

## 10. Hosted / BYOK accounting

| Check | Result |
| --- | --- |
| Hosted counters vs BYOK ledger separated | PASS in existing identity/budget code |
| Non-admin cannot read global remaining | PASS unit |
| BYOK never decrements $5 / $100 | PASS by billing-mode split (unit coverage in prior inference tests) |
| Application limits ≠ upstream Spur hard cap | Documented on `HostedUsage.billing_note` |
| Spur rates treated as verified provider prices | FAIL — catalog `pricing_basis` remains unverified; estimates must not be sold as Spur invoices |

---

## 11. Composio / OAuth

| Check | Result |
| --- | --- |
| Empty catalog no longer silent | PASS unit (Manual/CSV remain) |
| Live toolkit list | NOT TESTED |
| Judge OAuth (GitHub/Gmail/etc.) | NOT TESTED |
| Per-Clerk-user connection isolation | PASS existing identity scoping; live two-user OAuth NOT TESTED |

---

## 12. Security and two-user isolation

| Check | Result |
| --- | --- |
| Goal archive denied to other user | PASS unit (`403` or `404`) |
| Collection members must be owned | PASS service `_owned_ids` |
| Username uniqueness | PASS unit `409` |
| Profile private by default | PASS `privacy: "private"` |
| Live two-browser isolation | NOT TESTED this SHA |
| Secrets in report/logs | None copied |

---

## 13. Regression tests

Local (mocked / in-memory unless noted):

- `uv run python -m pytest apps/api/tests/test_production_upgrade.py` — 12 passed
- `uv run python -m pytest apps/api/tests/test_phase1_auth.py apps/api/tests/test_api.py apps/api/tests/test_behavior.py` — passed
- `uv run python -m pytest apps/api/tests/test_forecasting.py apps/api/tests/test_phase2_settings_api.py` — passed with the upgrade file
- `npx vitest run src/App.test.tsx` — 6 passed
- `npx tsc --noEmit` (web) — passed

These are **not** live provider proofs.

---

## 14. Remaining blockers and owner actions

1. **Signed-in production pass.** Google Clerk on https://buildnorth-delta.vercel.app is required for Spur, BYOK, Plugins OAuth, collections rows, and archive/create. This session reached the sign-in wall only.
2. **Hosted 0016 row proof.** Local applied. Render `db_migrate.py` runs on Docker boot against `PM_DATABASE_URL`. Unauthenticated `GET /api/v1/collections` is 401 (router mounted). Confirm `collections` rows after signing in.
3. **GitHub CI.** ESLint errors from the profile form are fixed. `ruff check .` still fails on hundreds of pre-existing findings. Vercel does not wait on that CI job.
4. **Live Spur/Anthropic** still $0.00; stay under $0.10 after a session exists. Spur catalog estimates remain unverified invoices.
5. **Warm Render** before judging. Cold start still dominates the first hit; warm `/health` median 155 ms.
6. **Async agents.** `Prefer: respond-async` is in the live bundle. Crash mid-run can leave `status=running` on the single Render worker.
7. **Composio OAuth** still needs a signed-in Plugins connection.
8. CSV upload column mapping still uses native `<select>`.

---

## 15. Judge-readiness assessment

**Code is on the live URLs; signed-in judge proof is still open.**

Vercel production is serving `0e2eaef` (bundle includes Hosted credits UI, create menu, and async agent polling). Render `/health` returns JSON when warm. Collections, profile, and dashboard routes exist (401 without a session). What remains is a Google-signed-in pass for Spur, BYOK, Composio, and hosted `0016` rows.

### Requirement matrix

| Requirement | Status |
| --- | --- |
| 1A.1 Deployed API recognizes Spur | NOT TESTED signed-in; API is up (`/health` 200) |
| 1A.2 Spur credits usable | NOT TESTED |
| 1A.3 Exact Spur model/API/tools | PASS code inspection (`tools=False`, json_object); live FAIL/NOT TESTED |
| 1A.4 Hosted workflows | NOT TESTED live |
| 1A.5 Spur tool calling investigated | PASS — catalog marks tools unsupported; agents must use compatible path |
| 1A.6 Compatible execution or precise limit | PASS — structured forecasting via json_object; tool-using agents limited |
| 1A.7 No hosted OpenAI/Anthropic fallback | PASS unit |
| 1A.8 Token accounting / ledger | PASS existing tests; live NOT TESTED |
| 1A.9 $5 / $100 preserved | PASS code; live budgets not reset |
| 1A.10 Verified Spur pricing | FAIL — not presenting estimates as verified |
| 1B Anthropic real inference | NOT TESTED (prior validation only) |
| 1B OpenAI BYOK | NOT TESTED |
| 1B AES-GCM / isolation / auto-activate | PASS prior unit; live isolation NOT TESTED |
| 1B BYOK ≠ hosted spend | PASS code |
| 1C Provider-backed discovery | PASS unit (no invented IDs) |
| 1C Searchable picker + persist | PASS frontend code |
| 1C Hosted allowlist only | PASS unit |
| 2A Measure first | PARTIAL — warm `/health` median 155 ms (n=5); authenticated page waterfalls missing |
| 2B React Query SWR | PASS code |
| 2C Dashboard batch + plugin cache | PASS unit |
| 2D DB/engine | PASS code; live query plans NOT TESTED |
| 2E Async agents | PASS code + unit (`Prefer: respond-async`); live NOT TESTED |
| 3A Empty catalog diagnosis | PASS code |
| 3B Judge OAuth | NOT TESTED |
| 3C Plugin browsing polish | PARTIAL |
| 4A Hide global budget | PASS unit |
| 4B Split Hosted/BYOK UI | PASS mocked e2e; live bundle contains `PlayItOut credits` |
| 4C Consistent primitives | PARTIAL |
| 5A Create menu | PASS unit; live bundle contains `New collection` |
| 5B Select mode | PASS code |
| 5C Safe deletion | PASS unit (soft archive) |
| 6A Collection model | PASS unit |
| 6B Collection graphs | PASS code |
| 6C Progress ≠ probability | PASS unit |
| 7A Profile | PASS unit |
| 7B Aggregated radar | PASS code |
| 8A Withheld explanation | PASS unit + persist |
| 8B Evidence form | PASS code |
| 9 Tests / typecheck | PASS targeted local; GitHub CI ruff still red on pre-existing issues; Vercel `tsc -b` PASS on `0e2eaef` |
| Hosted Supabase is the production database | PASS (intended: Render `PM_DATABASE_URL`; local `.env` still loopback) |
| Inspect migrations before apply | PASS local dry-run (0016 applied, none pending). Hosted inspected only via Render migrate-on-boot, not MCP. |
| `supabase db push` not used | PASS |
| 0016 applied on local DB | PASS (`127.0.0.1:54322`, `collections_table True`) |
| 0016 applied on hosted DB | NOT TESTED at row level (no session). Router is live (`/api/v1/collections` 401). |
| Render reads/writes hosted DB | PARTIAL — `/health` 200, authenticated routes 401, `/health/details` 404 by design |
| 9 Live deploy of this SHA | PASS Vercel `0e2eaef`. Render JSON `/health` 200 on the same API host |
| 9 Two-user live isolation | NOT TESTED |
| 9 Mobile/desktop live | NOT TESTED this SHA |

**Definition of done:** frontend/API SHAs are live. Remaining: signed-in Spur/BYOK/Composio under $0.10, hosted `0016` row proof, and authenticated navigation waterfalls.

---

## Signed-in production acceptance addendum — 2026-10-19

This section supersedes earlier statements that Google sign-in was unavailable. Tests used the signed-in administrator in Chrome against `https://buildnorth-delta.vercel.app` and `https://playitout-api.onrender.com`. Local tests and deployed behavior remain separate. Code repairs `3b85f67` and changelog `a5dd3a8` were pushed to `main`; production rechecks below must be read with their stated deployment state.

| Workflow | Status | Real browser evidence / limitation |
| --- | --- | --- |
| Admin session and navigation | PASS | Settings showed Administrator and $5.00/$5.00 personal, $100.00 global. Markets, Plugins, Settings and Profile opened in the same signed-in Chrome context; a full reload retained the session. Direct `/api/v1/me` response body was not independently captured. |
| Hosted `0016` tables | PASS (functional row proof) | Markets created collection `a9e16eaa-92a0-4dce-a26a-d0d6bc53e80f`; a full browser reload showed it again. Goal assignment changed it to 0/1 members. Profile GET showed 1 goal and 1 collection. These are authenticated Render-backed reads/writes of the new tables and profile columns. The migration ledger itself was not queried. |
| Markets / selection / collection | PASS | Goal selection enabled the move action; assigning the reading goal updated the collection count. Empty collection detail loaded. Goal deletion was not exercised because it would archive the only real goal. |
| Profile read / radar | PASS | Profile showed account details and an insufficient-evidence radar. No fabricated radar values were displayed. |
| Profile save | FAIL on old deployment; repair pending live recheck | Clicking Save profile twice at `/profile` returned `TypeError: Failed to fetch`. API CORS allowed GET/POST/PUT/DELETE but omitted PATCH, so browser PATCH preflight failed. `3b85f67` adds PATCH and a regression test. No profile data changed. |
| What If manual retry | FAIL on old deployment; repair pending live recheck | On reading goal `2771b9fc-89d1-5885-a080-a88eb0425ce7`, natural-language submission requested missing books-read count and a generic `rate`. Entering 5 books and rate 1 left Pricing pending before `Failed to fetch`; refresh showed no priced baseline. Local repair consumes manual count/rate evidence, names rate “Books per week,” retries queued scenarios, and persists composed explorations. A live numerical comparison is still unverified. |
| Evidence / GitHub source | FAIL UX; sync NOT TESTED | Evidence listed 49 unrelated sources and raw `GITHUB_*` capabilities; source plan said “Source plan unavailable.” Connected GitHub appeared. Local repair scopes the page to connected sources, validates owner/repository and activity selection, makes source planning on-demand, and fail-closes unsupported activity. Actual provider sync has not completed in browser. |
| Composio catalog | PASS | Plugins loaded 52 real provider entries; GitHub showed Connected and a connected account. A fresh OAuth transition was not exercised. |
| Settings / BYOK display | PASS for read; inference NOT TESTED | Anthropic key appeared validated, mode BYOK, model `claude-sonnet-5-5`; hosted Spur model `spur-glm-5-3` available. The live picker was cramped; CSS repair is local until deployment. No key material was read or printed. |
| Spur agent goal creation | NOT TESTED | No fresh hosted inference was initiated after the session's cost baseline proved ambiguous. Credit counters stayed $5.00/$5.00 when inspected. No agent completion is claimed. |
| Anthropic BYOK inference | NOT TESTED | Saved key validation was visible; validation alone does not prove model output. The ledger already showed 108 calls / 529,968 tokens / estimated $1.9796 before reliable per-pass accounting. No fresh BYOK inference is claimed. |
| Graph rendering / withheld reason | NOT TESTED | Existing reading goal had no published odds; collection had 0/1 measurable goals. Insufficient evidence states rendered, but no priced graph or withheld-forecast explanation was tested. |
| Mobile / console | FAIL / FAIL | At 390×844, collection progress text overlapped the title on Markets; local responsive fix awaits production recheck. Console warned that Clerk development keys were loaded on production. No additional console error was captured in the browser log sample. |
| Second-user isolation / invite redemption | NOT TESTED | No authorized second test session was available in this pass. Existing invitation rows were visible; no uncontrolled invitation was created. |

**Latency evidence.** Three warm unauthenticated `GET /health` probes returned 200 in 518, 277 and 188 ms (median 277 ms). These numbers exclude browser rendering, Clerk, authenticated DB queries and cold starts; they are not a before/after page-performance result. Authenticated routes visibly spent time in loading states, but the browser control's locator wait did not yield a reliable timed sample. p50/p95 authenticated navigation and API latency remain unmeasured, so no speedup is claimed.

**New code tests.** `uv run python -m pytest apps/api/tests/test_composition_overrides.py apps/api/tests/test_phase3_scenarios.py apps/api/tests/test_mcp_integration.py apps/api/tests/test_source_planner.py -q`: 39 passed. Profile PATCH CORS preflight regression: 1 passed. `npm run build`: passed; JS 949.99 kB uncompressed / 271.56 kB gzip, with Vite large-chunk warning. `npm run lint`: 0 errors, 10 warnings. Selected Ruff check still reports line-length issues, including pre-existing ones; broad Ruff baseline remains red. These results are local, not live provider proofs.

**Paid inference cost for this addendum:** no additional paid inference was intentionally run. An exact per-pass delta cannot be computed from the existing BYOK ledger, so $0.00 is not claimed as a measured provider bill. Hosted personal/global budgets were not reset.

**Judge-readiness:** **not ready for external invited beta/judges yet.** A real Spur agent goal and Anthropic BYOK completion, a priced What If retry with persistence, GitHub evidence sync, production PATCH repair, mobile repair, and authenticated p50/p95 measurements still need live proof. The production Clerk development-key warning is a configuration blocker; no production secrets or auth settings were changed during this pass.

---

## Post-deployment live acceptance — 2026-10-20 (supersedes the preceding addendum)

The same signed-in administrator Chrome session tested Vercel and Render after `3b85f67`/`a5dd3a8` deployed. Render's live logs identified its database as `aws-0-us-east-1.pooler.supabase.com:5432/postgres`. Functional reads and writes prove the `0016` collection/profile schema exists in that hosted database; the migration ledger was not queried. This is stronger evidence than a protected route's 401 response.

| Workflow | Status | Deployed browser/API evidence and limits |
| --- | --- | --- |
| Admin Google session, navigation, refresh | PASS | Administrator role and hosted budget appeared in Settings; Markets, Plugins, Settings, Profile and goal pages opened; full reload retained access. Render logged `/api/v1/me` 200, though its JSON body was not separately captured. |
| Hosted Supabase `0016` schema | PASS (functional) | Collection `a9e16eaa-92a0-4dce-a26a-d0d6bc53e80f` was created, reloaded and assigned a goal. Profile read returned goal/collection counts. Migration ledger version remains unverified. |
| Spur-hosted agent and goal persistence | PASS | Hosted mode produced a validated habit contract for four piano practices weekly; confirming created goal `71c86259-ac88-531b-84ea-adab6fc716f6`, present after full reload. Hosted usage rose 1,616 tokens; personal credit displayed $5.00→$4.99 and global $100.00→$99.99. |
| Anthropic BYOK agent and accounting | PASS | Saved validated key, selected `claude-sonnet-5-5`, generated a 12-session guitar contract and confirmed persistent goal `b436955c-7726-5748-b7b8-4aa8dad9823e`. Usage changed 108→109 calls, 529,968→532,811 tokens, estimated $1.9796→$1.9884 (+$0.0088). Hosted balance remained $4.99. Key material was not exposed. |
| Baseline and numerical What If | PASS with calibration limit | Reading goal `2771b9fc-89d1-5885-a080-a88eb0425ce7`: after entering five books and one book/week, baseline priced at 10.6% (rounded 11%). “Read 2 books per week” showed 11%→92%, +81.7 percentage points, explicitly exploratory/uncalibrated. Past What If persisted after full reload; Render logged parse, simulate and fast-reprice POST 200. “Read 30 minutes daily” remained unpriced because no minutes-to-books causal rate exists; the UI did not invent one. |
| Graph, Markets and withheld reason | PASS | Goal detail rendered the published 10.6% chart and controls; Markets tile showed 11%. Newly created goal displayed a withheld-forecast explanation instead of fabricated odds. |
| Collections / goal selection and deletion | PASS with progress limitation | Selection and move updated collection to 0/1 members. Collection detail and refresh worked. The test-created piano goal was selected, then archived through the browser confirmation; it disappeared from Markets while the UI stated forecast/evidence/usage history remains intact. Progress remained unavailable despite the reading goal's priced forecast; whether that is an intended current-state metric or a defect needs product review. |
| Profile read and edit | PASS | Profile rendered counts and insufficient-evidence radar; Save closed the editor after deployment. Render logged successful `OPTIONS /api/v1/profile` with PATCH allowed. Earlier pre-deploy failure was the CORS allowlist defect fixed in `3b85f67`. |
| Composio catalog / connection | PASS / NOT TESTED | Plugins showed 52 actual catalog entries and an existing Connected GitHub account. New OAuth authorization and a repository activity sync were not completed; connection status alone does not prove integration ingestion. |
| Evidence and source controls | PASS (display) / NOT TESTED (ingestion) | Deployed Evidence showed one relevant connected GitHub source, an on-demand “Find relevant sources” control, manual evidence composer, and repository/activity settings. After `5496a97`, Chrome showed full-width upload and manual forms with proper spacing. On-demand agent planning and provider sync were not run within the cost ceiling. |
| BYOK/hosted Settings | PASS (behavior and post-fix display) | Mode switch, model selection, saved key state and hosted counters worked. After `5496a97`, signed-in Chrome showed the Anthropic picker without the hosted Spur model and the credit button at normal height. No additional provider call was made. |
| Invitations / second-user isolation | NOT TESTED in this pass | Earlier Pass 06 created/redeemed/revoked a bounded invite. No new invite or authorized second account was used here, so isolation is not claimed. |
| Mobile responsiveness | PASS for overlap repair; limitation remains | A fresh signed-in Chrome tab at 390×844 showed the collection title, progress label and 0/1 count on separate lines without overlap. Settings and bottom navigation fit. Markets cards still leave substantial empty vertical space and a small loading indicator, so visual polish is incomplete. |
| Console / unexpected failures | FAIL (configuration) | Console showed Clerk development-key warning on production. No other console error was seen in the captured sample. A newly opened Chrome tab later stayed at “Checking your session”; its cause and repeatability are unproven. |

**Cost boundary.** BYOK ledger increased from the pre-pass $1.9796 to $2.0612 after the agent and What If checks: +$0.0816 estimated, 108→113 calls, 529,968→552,643 tokens. Hosted credits displayed about $0.01 consumed. The application's combined estimate is about $0.09, under the $0.10 ceiling; an actual upstream Spur invoice was not available. No additional paid calls should be made in this pass.

**Performance.** Warm unauthenticated `/health` measurements were 518/277/188 ms (median 277 ms); a later probe was 607 ms. In a fresh signed-in Chrome tab, Plugins navigation showed a loading state at 0.3 seconds and the 52-item catalog at about 20.5 seconds. Settings shell appeared at 0.07 seconds, invitations by 7.0 seconds, and inference balances/ledger by 9.5 seconds. These are coarse end-to-end UI observations with external catalog and sequential auth/data loading, not isolated API timings; the sample is too small for p50/p95 or a valid old-versus-new speedup claim. The published What If calculation took roughly 20+ seconds end to end, including agent parsing and baseline work. This remains a judge-experience concern.

**Visual evidence:** [mobile Markets screenshot](docs/pass06_mobile_markets.png), [desktop Markets screenshot](docs/pass06_desktop_markets.png), [post-fix Evidence screenshot](docs/pass06_evidence_after.png), and [post-fix Settings screenshot](docs/pass06_settings_after.png) captured from the signed-in deployed browser. They show the repaired mobile overlap, Evidence form and Settings button, plus the remaining empty card space.

**Follow-up code and verification.** Commit `5496a97` makes unpriced scenarios persistent with an actionable explanation, constrains the manual Evidence layout, prevents the hosted Spur model leaking into the Anthropic BYOK selection, and fixes stretched credit-setting buttons. Targeted backend tests: 33 passed. Settings web tests: 2 passed. Production web build passed (950.27 kB JS, 271.64 kB gzip; chunk-size warning). `git diff --check` passed. Vercel serves `index-CcBgKG21.css`, and Render's deploy dashboard shows `5496a97` Live. Evidence form layout passed a signed-in browser recheck; unpriced persistence remains local-test-only because no further paid inference was run.

**Deployment-transition failure:** on `/settings` immediately after the Render rollout, hosted usage and inference settings showed “Failed to fetch” while the already-loaded admin identity and budget remained visible. No HTTP status was captured in browser network tooling. This coincided with Render's switch from `a5dd3a8` to `5496a97`. After Render confirmed `5496a97` Live, a full reload restored inference settings, Anthropic validated-key state, 113-call BYOK ledger and $4.99/$5.00 hosted balance. Treat the first failure as transient deployment availability; no persistent frontend or provider defect was established.

**Judge-readiness:** core hosted/BYOK agents and numerical exploratory forecasting now have real production proof. **Not ready for broad external invited beta or judges** until Clerk production keys are configured, slow authenticated views and empty card space are addressed, follow-up UI fixes are deployed/rechecked, and connector ingestion is proven. No production secrets or budgets were changed during this acceptance pass.

---

## Critical product remediation in progress — 2026-10-20

This tracks 19 concrete outcomes in the latest request. Base commit: `2a5b790629832bbc8ae0c1ed3a209323bef01006` on `main`. **This working tree has not been committed or deployed.** Production still serves the earlier build. Local implementation and fixture tests are marked PARTIAL until production acceptance. No new paid inference was initiated.

| # | Outcome | Status | Evidence and remaining work |
| --- | --- | --- | --- |
| 1 | Minimal goal cards, genuine odds/change | PARTIAL | Local cards omit category and invented `+0.0%`; desktop/mobile fixture browser checks pass. Production recheck pending. |
| 2 | Minimal Markets heading/actions | PARTIAL | Local heading and toolbar simplified; fixture browser checked. Production recheck pending. |
| 3 | Collection cards with portfolio odds/change | PARTIAL | Local card uses new portfolio fields and a dash for missing data; production recheck pending. |
| 4 | Equal-weight portfolio math and comparable change | PARTIAL | Pure calculation over valid published histories and UTC-day comparable membership; unit tests pass. No live collection with multiple priced goals was available. |
| 5 | Multiline chart and sparse histories | PARTIAL | Local chart uses all goal histories and one-point dots; fixture browser checked. Multi-series live interaction and keyboard details still need acceptance. |
| 6 | Collection rename, membership, deletion | PARTIAL | Local edit and confirmation flows, name conflict guard, optional Personal rename. Hosted read/write for this version not tested. |
| 7 | Compact Photos-style selection | PARTIAL | Local goal/collection selection, Cancel, bottom bar, archive/delete confirmation, disabled Share, More/Move; fixture browser checked. |
| 8 | Restrained Profile header and editor | PARTIAL | Local composition and styled dialog inspected at desktop/mobile widths. Production acceptance pending. |
| 9 | Private uploaded profile image | PARTIAL | JPEG/PNG/WebP validation, bounded WebP re-encode, owner-keyed storage, upload/replace/remove and crop-position controls, plus additive `0017` migration; local API and fixture browser tests pass. Hosted persistence and isolation not tested. |
| 10 | Custom radar dimensions | PARTIAL | User-defined ordered dimensions and goal assignments, unknown scores remain unfilled; unit test and fixture browser pass. |
| 11 | GitHub repository picker and real record | PARTIAL | Local authorized-resource picker replaces typed owner/repo. No actual provider record fetched this pass. |
| 12 | Notion page picker and real content | PARTIAL | Local page picker, current content-fetch capability preference and revision-aware dedupe; real `Oct 20th book report` content was inspected in Notion, but no provider sync or goal update was run. |
| 13 | Resource relevance | PARTIAL | Book-report title promotes Notion for a reading goal in a unit test. Live source-plan failure remains undiagnosed; its model call was avoided under the spending restriction. |
| 14 | Sync result and durable receipt | PARTIAL | Provider failures surface and empty responses create no synthetic records. New goal-level job and receipt persist stages, counts, workflow and forecast outcome. Additive `0019` scopes raw-record deduplication by owner and links fetched records to jobs for manual retry after failure. No real double-sync result or hosted database proof exists. |
| 15 | Async, restart-safe sync and latency target | PARTIAL | POST now acknowledges a persisted job; a worker claims queued work and marks stranded active work timed out without replaying billable inference. Local restart-like test and browser reload polling pass. Hosted restart, authenticated p50/p95 and sub-two-second proof remain. |
| 16 | OAuth Pending to Connected automatically | PARTIAL | Locally, saved pending/connected accounts are included even when absent from the first catalog page, allowing polling to find them. Fresh real OAuth transition not tested. |
| 17 | Minimal copy and styled controls across routes | PARTIAL | Markets, collection detail, Profile, Plugins, and source workspace revised. Full route-by-route visual and console audit remains. |
| 18 | Preserve forecasting/auth/What If regressions | PARTIAL | Full backend suite passed after the seed upsert was updated for `0019`; 64 web unit tests and 14 fixture-backed browser cases pass. No deployed flow test. No probabilities, histories, budgets, or credentials changed. |
| 19 | Deployed authenticated desktop/mobile acceptance | NOT TESTED | Existing signed-in Chrome confirmed old production defects and real Notion page. This tree was not deployed, so no new authenticated acceptance or before/after production screenshots exist. |

**Local verification:** the full backend suite and isolated Postgres migration tests passed, including two owners ingesting one external event ID. Web production build passed (959.66 kB JS / 274.11 kB gzip; Vite chunk warning); ESLint passed with zero errors and ten existing warnings; 64 Vitest cases passed. Fourteen fixture-backed desktop/mobile Playwright cases passed, including photo crop/upload/reload/remove and sync reload/polling. Architecture, migration sanity, and `git diff --check` passed. Local after screenshots: `apps/web/test-results/remediation-markets-desktop.png`, `remediation-markets-mobile-chromium.png`, `remediation-profile-desktop.png`, `remediation-profile-mobile-chromium.png`, `remediation-evidence-sync-desktop.png`, and `remediation-evidence-sync-mobile-chromium.png`. The authenticated production baseline was inspected but no before screenshot artifact was saved.

**Performance:** no trustworthy before/after authenticated latency sample was captured. Prior warm `/health` numbers do not describe Markets or sync. Instrumentation is local; deployed p50/p95 is unavailable. This remains a release blocker.

**Release decision:** local verification and release preparation are in progress. Migrations `0017`–`0019` were applied to isolated local Postgres; hosted deployment and acceptance are outstanding. Actual GitHub/Notion agent sync needs explicit approval for additional paid inference under the request's spending constraint.

---

## Superseding 19-outcome production status — 2026-10-21

The preceding “in progress” section describes the earlier local tree. The remediation has since been pushed to `main`, migrations `0017`–`0019` ran on hosted Supabase during Render startup, and the signed-in application was exercised in Chrome. Render `b395e37` is live for the stable source-identity repair. `bb47d68` is the subsequent web presentation correction; its deployed visual state must be checked separately before its appearance is counted as passing.

| # | Outcome | Status | Production evidence and remaining limit |
| --- | --- | --- | --- |
| 1 | Goal cards with genuine odds/change | PASS | Signed-in desktop/mobile Markets showed compact title, odds and true daily change or dash, with smaller sparse-chart space. The final `pp` wording from `bb47d68` awaits deployed visual recheck. |
| 2 | Minimal Markets heading/actions | PASS | “Your outcomes” and compact Select/create controls were visually inspected and used. |
| 3 | Collection cards as portfolio summaries | PASS | Live collection showed its priced member's odds in the shared card hierarchy; sparse layout was refined after visual review. |
| 4 | Equal-weight portfolio and comparable change | PARTIAL | Pure calculation and tests pass; live data has only one priced member, so multi-member weighted arithmetic has fixture coverage rather than production proof. |
| 5 | Multiline, sparse-history chart | PARTIAL | Single-series and sparse live states plus fixture multi-series desktop/mobile interaction passed. No live collection with two priced goals exists to verify real multi-series appearance. |
| 6 | Collection rename/membership/delete | PASS | Hosted collection rename to Personal, membership updates and deletion semantics were exercised; member goals persist. |
| 7 | Compact Photos-style multi-select | PASS | Desktop/mobile selecting, deselecting, Cancel, contextual actions, disabled Share and confirmation were exercised; goal archive remains soft. |
| 8 | Restrained Profile and editor | PASS | Signed-in desktop/mobile Profile and edit controls were inspected; save/reload passed. |
| 9 | Private profile image | PARTIAL | Owner-scoped API, content validation and upload/replace/remove passed tests and fixture browser reload. Live Chrome file upload is blocked by its extension file-URL permission, so production image persistence cannot be marked PASS. |
| 10 | Custom radar dimensions | PASS | Reading dimension assigned to the reading goal, persisted after full live reload; unknown score stayed unfilled. |
| 11 | GitHub resource selection and record | PASS | Picker listed real accessible repositories; `MrSujalThapa/buildnorth` Commits was saved and fetched in production. |
| 12 | Notion page selection and content | PASS | The real `Oct 20th book report` was selected; a document-shaped `NOTION_GET_PAGE_MARKDOWN` response was ingested. Its selected page name is shown after re-save. |
| 13 | Resource relevance | PARTIAL | Reading-goal ranking contract test passes and the actual book report was selectable. A live agent-generated relevance explanation was not separately confirmed. |
| 14 | Evidence sync and durable receipt | PASS | Live first ingestion raised exploratory odds 10.6% to 15.1%; subsequent stable-fingerprint repeat logged `records_read=1`, `records_new=0` for both providers and showed “No new updates” without repricing. Earlier retries exposed and led to fixes for document payloads, failed-run replay and volatile provider IDs. |
| 15 | Async/restart-safe sync and latency | PARTIAL | Persisted queued/running/completed stages and browser polling worked, including manual retry after failed runs. A deploy interrupted an active worker and its job timed out as designed. The sub-two-second authenticated navigation target and p50/p95 remain unproven. |
| 16 | Pending OAuth auto-update | PARTIAL | Pending polling and expired-authorization refresh have fixture tests. No new provider OAuth transition was run in the live session; existing connections were already Connected. |
| 17 | Minimal copy and styled primitives | PARTIAL | Markets, collections, Profile, Settings, Plugins and Evidence were visually revised and inspected at desktop/mobile. Remaining old copy in peripheral routes and the production Clerk development-key warning mean no full route-by-route accessibility/console PASS is claimed. |
| 18 | Preserve forecasting/auth/What If | PASS with test-environment limit | The preexisting hosted/BYOK goal, numerical What If, auth and immutable forecast paths were tested earlier in production and not intentionally altered. Targeted sync tests pass; the current full backend suite cannot run to completion because local test Postgres is unavailable. |
| 19 | Deployed desktop/mobile acceptance | PARTIAL | Signed-in desktop/mobile screenshots and interactions cover the highest-priority routes. Production photo upload, a fresh OAuth transition, multi-priced collection and complete performance target remain unverified. |

**Sync evidence and cost.** On the final repeated production run, Render logged GitHub at 10:27:42 EDT and Notion at 10:27:50 EDT with one record read and zero inserted for each. The browser showed “No new updates” and 15.1% current odds. The BYOK usage ledger was 114 calls / 558,127 tokens / estimated $2.0723 before this investigation and 119 / 590,627 / $2.1610 after, a measured application-estimate increase of $0.0887. No inference charge was attributed to the zero-new-record final run. The $50 user ceiling was not approached. These are exploratory probabilities and estimated usage, not measured forecast accuracy or provider invoices.

**Performance evidence.** The live Plugins view previously took about 26 seconds from a fresh signed-in navigation, even after the local default catalog was introduced. Render logged repeated Clerk verification around 0.2–0.5 seconds and identity resolution around 0.7–1.6 seconds; one authenticated Plugins request consumed roughly nine additional seconds. Sync provider calls in the final two runs took roughly 7.4–11.4 seconds each. Jobs return promptly and display stage feedback, but the five-minute-blocking user experience is not fully resolved by this: authenticated page p50/p95, query counts and a sub-two-second navigation proof are outstanding. The current web build is about 958 kB JS / 274 kB gzip and still emits the chunk-size warning.

**Verification.** `uv run python -m pytest apps/api/tests/test_mcp_integration.py apps/api/tests/test_goal_sync_jobs.py -q` passed 32 tests; the current web adapter test passed three; `npm run build` passed; `npm run lint` reported zero errors and ten existing warnings. An attempted plain `python -m pytest` used system Python without pytest and was rerun through `uv`. An attempted full backend suite hit local `psycopg.errors.ConnectionTimeout`; it is not reported as passing for this final revision. Earlier isolated Postgres and fixture-backed Playwright runs remain recorded above. Final desktop/mobile visual artifacts include `docs/remediation_after_collection_live.png`, `docs/remediation_after_collection_mobile_live.png`, `docs/remediation_after_profile_mobile_custom_live.png`, `docs/remediation_after_source_sync_live.png` and `docs/remediation_repeat_sync_no_updates_live.png`.

**Release limits.** Production still uses Clerk development keys. A browser extension permission prevents a real production photo upload from this controlled Chrome session; broadening that permission would expose local file URLs. Fresh OAuth completion, a real two-priced-goal collection and measured p50/p95 remain open acceptance checks. The live source-ingestion and no-duplicate behaviors are proven within the selected Notion page and GitHub repository scope.

### Final Markets release check — 2026-10-21

Vercel marked `77d96c1` Ready. In the signed-in deployed app, desktop and 375 px mobile Markets showed one coherent grid of collection and goal cards. The collection chart now uses the observed data range, so its 10.6% to 15.1% trajectory is legible. Goal and collection changes both displayed `+4.4 pp today`. Selecting and deselecting the collection changed the action bar between one and zero selected; Cancel exited selection. Opening the collection worked at both sizes. Its detail showed 15% rounded odds, `+4.4 percentage points today`, an upward chart, and an expandable calculation showing one published member at 15.1%. Screenshots: [desktop Markets](docs/remediation_markets_final_desktop_live.png), [mobile Markets](docs/remediation_markets_final_mobile_live.png), [desktop collection](docs/remediation_collection_final_desktop_live.png), [mobile collection](docs/remediation_collection_final_mobile_live.png), [expanded calculation](docs/remediation_collection_expanded_mobile_live.png).

The `bb47d68` percentage-point wording and readable extracted reading events were also checked in the deployed browser, superseding the earlier pending visual note for outcome 1. The final Markets change leaves outcomes 1–3 and 7 at PASS. Outcomes 4–5 remain PARTIAL because only one member has live priced odds; a two-priced-goal fixture passed desktop/mobile interaction and screenshot review. Outcomes 9, 13, 15–17 and 19 retain the limits in the matrix above.

### Extended remediation status — 2026-10-21

The newer autonomous observability and behavioral-execution brief extends the original 19-item matrix. The prior 11 PASS labels are limited to their stated tests and are not an acceptance of these new requirements.

**PARTIAL — execution-profile correction.** `e738eb6` removes goal-progress fallback and unpaired action trials from the radar; six execution traits now separate behavior from interest-area filters. Targeted behavior tests and desktop/mobile fixture browser paths pass. Durable commitments, chronological validation, calibrated execution probabilities and What If integration remain open.

**Follow-up in progress:** additive `0021` introduces durable planned windows and immutable outcome revisions. Profile and What If load explicitly scored trials; missing/cancelled outcomes remain unknown. A dual-horizon estimator retains long-term history. A chronological synthetic evaluation is recorded in the improvement changelog, but it does not establish real-user calibration. No live commitments were created. Real provider-linked completion, natural recurring habit capture and production behavioral E2E remain open. A signed-in production desktop screenshot showed the new six-axis empty radar but its left label was clipped; a centered layout correction passed desktop/mobile fixture browser review and awaits deployment.

**PARTIAL — persisted exact-resource monitoring foundation.** Migration `0020` adds owner-scoped watches, pause/revoke state and scheduling checkpoints. Scheduled jobs use the existing evidence/forecast pipeline with an exact approved-resource allowlist and recheck active consent before reading. A standalone scheduled runner is prepared. It has not been run against production, and no paid external cron service has been provisioned. Parent-scoped Notion descendant discovery, provider triggers, automatic new-report E2E, monitoring UI and ongoing worker reliability remain open. Autonomous observability is not PASS.

**PARTIAL — latency visibility.** `f672f76` adds correlated route-duration logs and a bounded client session retry state. No valid authenticated p50/p95 before/after result has been collected for this revision. Free Render cold starts remain a release blocker for responsive navigation and reliable in-process scheduling.

**Measured samples, still PARTIAL:** after `f672f76` reached Render, authenticated Profile GET samples were 3.42 and 5.06 seconds; Settings inference GET was 4.28 seconds, and a redundant Settings `/me` GET took 4.82 seconds. The newest code removes that automatic duplicate request and retains the five-minute discovered-model catalog across production requests. These optimizations await deployment and a warm before/after p50/p95 sample. They do not solve free-tier cold starts or establish a sub-two-second target.

No new live data was seeded and no paid inference was run for this extension. The original 19-item statuses stay as previously recorded until each is rechecked after deployment.

**2026-10-21 continuation:** `3d75ff5` shipped explicit commitment windows, versioned outcomes, a dual-horizon behavior estimator, synthetic chronological holdout evaluation, low-cost source suggestions, the centered empty radar and Settings request reduction. `51c8998` corrected watch scheduling so an active sync cannot consume a due checkpoint without queuing a job. `931eb50` corrected an AuthGate test lint error. Focused backend behavior/What If/source/watch tests and the frontend production build passed locally. The synthetic evaluation is not empirical calibration, and neither the commitment API nor watch API is marked consumer-ready. No real commitment or watch was created in the user's production account.

The CI run for `3d75ff5` failed on an AuthGate test lint rule; that specific error was fixed in `931eb50`. Repository-wide Ruff still reports hundreds of pre-existing violations when run locally, so a green full lint gate is not claimed. The controlled signed-in Chrome session became unavailable during this continuation, so the latest production deployment, migration `0021`, warm authenticated p50/p95 and updated radar screenshot require a fresh browser verification. All extended criteria and original matrix items depending on those checks remain PARTIAL or NOT TESTED, not PASS.

**2026-10-21 CI correction:** `940562d` passed the complete GitHub CI workflow, including a real Postgres migration, full tests, web build, architecture and migration checks, demo seed, and fail-closed optional-provider check. `c082569` also passed. The strict Ruff and mypy commands still expose 576 and 380 historical findings respectively; the default gates now fail on new findings while retaining `lint:strict` and `typecheck:strict`. These are debt baselines, not strict-compliance PASS labels. The live Render migration and authenticated browser checks remain unverified.

**Parent watch expansion in progress:** A selected Notion parent page can be watched for accessible child pages through the documented read-only block-children capability. New child IDs are validated, pagination and traversal bounded, and the queued watch is rechecked against active consent before read. Local tests verify nested discovery and revocation. The code has no live new-report test or externally provisioned scheduler yet, so autonomous Notion evidence remains PARTIAL.

CI for `c3a7ca9` stopped at four type errors in its new test, before running the full suite. The test typings were corrected; the watch worker now persists success/error outcomes and treats an active watch with no approved recipe as actionable failure. Seventeen focused watch, job and Notion-scope tests pass locally. A follow-up CI run is required before this slice can be called regression-verified.

Four targeted Playwright cases passed on desktop and mobile, including the two-series chart fixture; the web production build passed. The last desktop/mobile console sample contained only the Clerk development-key warning. A fresh Render `/health` request after inactivity took 29.7 seconds to return 200, confirming a cold-start risk. No authenticated p50/p95 or sub-two-second claim is made. No additional paid inference was used for this release check.

**2026-10-22 watch controls, still PARTIAL:** CI run `39706862097` passed the full workflow for the Notion parent-watch and result-tracking changes. A saved, approved source now has compact Watch area/Monitor, Pause, Stop and Restart controls, plus its last actionable error. The controls use the owner-scoped watch API and are guarded by the build-time `VITE_BACKGROUND_MONITORING=true` flag. The production build leaves that flag off until a reliable external scheduler is provisioned; enabling a watch without one would falsely promise automatic observation. Desktop and 390 px mobile mocked Playwright interactions passed and screenshots were inspected (`apps/web/test-results/source-watch-desktop.png`, `apps/web/test-results/source-watch-mobile-chromium.png`). This is an interaction check, not a real production watch or new-Notion-report E2E. The scheduler approval remains outstanding, and no paid infrastructure or inference was started.

**Bundle-size iteration:** Route-level React lazy loading moved secondary views into separate chunks. In the same local build environment, the entry JS shrank from 959.6 kB / 274.1 kB gzip to 801.3 kB / 230.4 kB gzip; six App tests and four desktop/mobile Evidence/What If browser cases passed. This is a bundle result, not a measured warm authenticated p50/p95 or sub-two-second navigation result. The entry still exceeds Vite's 500 kB warning threshold.

CI runs `39707197225`, `39707373748` and `39707480389` all passed. A subsequent combined local mocked-browser rerun passed 18 desktop/mobile paths across Markets, collections, Profile, source relevance/selection, sync persistence, watch controls and What If. Those paths do not substitute for authenticated deployed E2E or establish automatic ingestion.

### 2026-10-22 authenticated production continuation and Cron blocker

Merged `5a893a850f3521ce756379ded5e0f071dcc0d062` (#9) passed CI and reached Render and Vercel. Authenticated desktop Chrome verified a single Plugins search field and canonical catalog entries, preserved connected GitHub/Notion identity, green/red/neutral Markets history presentation, and selection mode with count, Archive/Delete, disabled Share, Move to, and Cancel. The connected Notion account returned real resources; a two-page reading source recipe survived reload. Two production manual syncs returned no relevant goal change and then no new updates, without duplicate evidence. This is evidence of repeat-sync behavior only; automatic discovery and a new relevant report were not verified. The Notion picker still exposes an ISO-like title for one page that Notion itself displays as a date mention.

An existing withheld financial goal received two explicitly user-provided manual state observations and published 3.9% odds. Its production Change scenario displayed 83% conditional, 78% follow-through, and 66% execution-adjusted estimates; Futures returned distinct scenario outcomes and Compare kept two custom interventions distinct. These are live product outputs, not a new model-calibration claim. Reverse generated paths, but the improved consumer wording in #9 was not rechecked after deployment. No new personal goals, commitments, GitHub evidence, or profile image were created.

The approved Render Cron Job was prepared on `*/15 * * * *`, Docker command `uv run python -m personal_markets.integrations.watch_runner`, cheapest displayed `0.5c-512mb` at $0.00016/min. Billing showed $50 promotional credits and no card. Submitting the job opened Render's Add Card dialog, so **no Cron Job was created or deployed**. Official Render documentation specifies a $1/month Cron minimum and credit application to invoices; the live card gate establishes that this account cannot deploy it cardless. No paid fallback or web-service upgrade was made. A minimal, unlinked environment group was saved for the runner. Render's group-creation form unexpectedly exposed masked secret values to browser accessibility output; no values are reproduced here or in source control. Credential rotation needs a coordinated maintenance action before the group is attached. No scheduled execution, asleep-web-service processing, automatic Notion update, run duration, charge, or end-to-end latency exists to report. Autonomous production monitoring remains **BLOCKED** by Render's payment-method requirement.

Open PR #10 (`70d5c3c` plus subsequent watch mutation fix on `codex/watch-source-controls`) supports controls for every approved resource in a multi-resource recipe. Focused frontend typecheck and the resource-ID test pass. The production `VITE_BACKGROUND_MONITORING` flag remains off. Production mobile viewport verification, real profile photo upload, genuine new-child Notion E2E, fresh OAuth transition, and a complete rerun of the original 19-item matrix remain **NOT TESTED/PARTIAL** as previously scoped. Previously verified items retain their narrow evidence; this addendum does not elevate them to blanket PASS.

**2026-10-23 follow-up:** The two-resource Watch/Pause/Stop/Restart interaction passed desktop and 390 px mobile mocked Playwright paths (2/2); screenshots at `apps/web/test-results/source-watch-desktop.png` and `source-watch-mobile-chromium.png` were inspected. This verifies the new control state and layout only. PR #10 at `1f116068cc5eb07997560996d36590f1b1b28471` awaits CI and deployed verification; the Render Cron blocker above still prevents live automatic-observation acceptance.

**2026-10-23 deployment correction:** PRs #10, #12, #11 and #13 passed CI and merged as `6778b59`, `56d5c08`, `0d89151` and `8dcd3e0`. Render `/health` reported `8dcd3e080ce4` live. The authenticated production Notion picker now displays the date-mention title `@April 27, 2026 4:15 PM` for the same authorized provider page URL that previously appeared as an ISO timestamp. This is a production presentation fix, not an evidence-ingestion run. The provider-status boundary in #13 has test coverage: external `completed` and `missed` labels remain activity hints and do not become personal commitment outcomes. Its live behavioral effect has not been exercised with new production evidence.

The user created Render Cron Job `playitout-source-watch` (`crn-dbdob93rjlhs73e07dhg`) on the approved `*/15 * * * *` schedule, Docker command `uv run python -m personal_markets.integrations.watch_runner`, and 0.5c-512mb plan. The initial environment lacked `COMPOSIO_API_KEY`; after action-time authorization, the prepared `playitout-watch-runtime` group was moved into the Production environment and linked to the job. The Render UI showed the group linked with masked values and the #13 commit live. At this checkpoint its Runs page still showed **no successful runs**. Scheduled execution, due-watch database effects, asleep-web-service behavior, and new Notion report detection therefore remain **NOT TESTED**, and automatic monitoring remains **PARTIAL**. No live watch or synthetic evidence was created. Billing displayed $0.00 accrued/projected and $50.00 promo credit; an automated Render chat bubble also claimed $7/month for the compute size, which conflicts with Render's official cron billing description ($1 monthly minimum plus active runtime). The actual charge requires a completed run and refreshed billing review; do not assert a $1 final invoice yet.

**2026-10-23 Cron execution and live watch:** The first scheduled run at 16:15 UTC failed before source processing because the copied BYOK key map was malformed. Manual retests exposed missing Clerk issuer and a malformed database URL. The 16:30 scheduled run began before the final environment update and failed on the old URL. The Cron configuration now uses `uv run --no-sync python -m personal_markets.integrations.watch_runner` to avoid reinstalling development dependencies on each run; the stored database URL was privately compared to the production web service's value after saving. A manual run from 16:32:01 to 16:32:46 UTC completed successfully, reached hosted Supabase, logged `source_watches_scheduled=0`, `processed=0`, and `source_watch_runner_finished duration_seconds=2.695`. This proves independent execution and clean exit; it does not prove observation. Render billing then showed $0.00 accrued, $0.27 projected for October, and $50.00 remaining credit. Its generic $7/month chat notice is inconsistent with the Cron billing page and should not be treated as a measured charge.

Vercel's production `VITE_BACKGROUND_MONITORING=true` setting was added and deployment `FRPFxhfjWrD5hEsM7BMcc3tDGqfD` reached Ready on commit `8dcd3e0`. In the authenticated production Evidence page, “Watch 2 areas” created two active owner-scoped Notion watches for the previously saved pages; the page displayed “Monitoring 2 of 2” with Pause and Stop controls after reload. A real screenshot was inspected. The accessible Notion resource search returned no “Book Reports” parent, so these watches cover two specific pages and do **not** establish new sibling report discovery. The first scheduled run with due watches, duplicate handling, and forecast propagation is pending; no new page or synthetic personal evidence was created. Authenticated session verification initially timed out twice after the Vercel deployment, then recovered on retry despite a sub-second `/health` response. That latency remains a release issue, not a PASS.

**2026-10-23 scheduled-run finding and correction in progress:** Render's Runs page now shows six consecutive successful scheduled invocations from 16:45 through 18:00 UTC, at the approved 15-minute cadence. The first lasted 55.3 seconds total and the latest 44.7 seconds total; the 16:45 and 18:00 app logs both show `source_watches_scheduled=0`, `processed=0`, with 2.811 and 2.567 seconds inside the app. These runs prove scheduling and hosted database startup but **not** watch processing or evidence updates. The web service also calls `enqueue_due()` every minute while awake, which can advance due checkpoints before Cron sees them and prevent a Cron processing demonstration. This branch removes that competing scheduler and reserves watch-job claims for the Cron runner; manual Sync remains on the web worker. Focused job/watch tests pass, including a real isolated Postgres claim test; desktop and 390 px mobile mocked watch-control tests pass (2/2), and both screenshots were inspected. This correction awaits CI, deployment and a subsequent scheduled run with `processed>0`. The asleep-web-service and genuinely new Notion child E2E remain unverified. No original 19-point status is elevated by successful empty runs.

**2026-10-23 production watch processing:** PR #14 passed all CI checks and merged at `638bc4196aeae9638a22e0732d7e681851edd8a2`; both Render services and Vercel reached that commit. The two already approved Notion watches were stopped and restarted through the authenticated Evidence controls to make their checkpoints due. The next scheduled Cron run started at 18:30:38 UTC and finished successfully at 18:31:50 (Render duration 1m12s). Its app logs show `source_watches_scheduled=2`, `processed=1`, app duration 16.811 seconds, two `NOTION_GET_PAGE_MARKDOWN` provider calls, and one normalized record read with `records_new=0`. The existing record was ignored as a duplicate; no forecast workflow or paid inference was invoked. The 19:00 scheduled run processed zero watches because their next check was not due. The live Evidence page still showed “Monitoring 2 of 2” and “No new updates,” matching the duplicate outcome. This verifies scheduled, owner-approved, durable processing independently of a browser action. It does **not** establish that the web service was asleep during the 18:30 run, that a newly created child page is found, or that a valid new observation reprices a forecast. Those remain NOT TESTED/PARTIAL. Billing still showed $0.00 accrued, $0.27 projected for October, and $50 credit after these runs; the billed charge and full-month amount are not settled.

**Warm navigation sample, still PARTIAL:** During a deployed authenticated Evidence reload at 18:25 UTC, Render recorded `/api/v1/plugins/connected` at 8,680 ms (two DB queries totaling 325 ms) and saved source recipes at 9,085 ms (three DB queries totaling 639 ms). Correlated identity logs showed Clerk JWT verification at 0–1 ms and owner lookup mostly 69–189 ms, with one 1,244 ms outlier. The remaining route time is not yet attributed, so no performance improvement or under-two-second claim is made. A browser reload briefly showed “Loading connected sources…” before the saved watches rendered; the final desktop screenshot was inspected. A representative authenticated p50/p95 remains outstanding.

The next instrumentation change records database connection acquisition separately from statement execution in `Server-Timing` and request logs. It is tested locally but awaits deployment and a new authenticated sample; it does not itself reduce latency.

An additional scoped optimization defers Composio SDK client construction until a provider operation actually needs it. Connected-source and saved-recipe navigation only needs local persisted rows. Thirty-one focused integration tests pass locally; CI, deployment and authenticated before/after measurements remain pending, so this is not a performance PASS.

The Notion picker also now follows bounded search pages when the Composio action's current input schema explicitly permits `start_cursor`. It stops after 100 results, five pages or a repeated cursor. This addresses a first-page discovery limit but cannot grant access to pages the Notion integration was not shared with. Production Book Reports parent discovery remains unverified.

### 2026-10-23 current-branch acceptance checkpoint

PR #21 merged as `64ea6ee`; Render API and Vercel production reached that commit. It preserved the existing code, added the course standing arithmetic, and removed paid inference from connected-source suggestions. PRs #18–#20 remain separate drafts; Pass 08 was not started. The original remediation is **not complete**. The statuses below require the whole outcome, not merely an API route or fixture test. Earlier narrow checks remain cited above.

| # | Original outcome | Status | Current evidence or precise gap |
| --- | --- | --- | --- |
| 1 | Goal cards, real odds and daily change | PASS | Previously signed-in desktop/mobile Markets and later final collection screenshots show real odds and `pp` changes; untouched by #21. |
| 2 | Markets heading and actions | PASS | Previously signed-in desktop/mobile heading, create and Select interactions; untouched by #21. |
| 3 | Collection cards matching goals | PASS | Previously signed-in desktop/mobile collection card and detail screenshots; untouched by #21. |
| 4 | Weighted portfolio | PASS | Signed-in `Career & company` showed 3/3 priced members at 76.5%, 94.6%, and 90.5%; equal-weight mean 87.2% displayed as 87%. The expanded calculation explicitly identifies the summary as an average, not a joint success probability. |
| 5 | Interactive multiline chart | PASS | The same real collection rendered three distinct published-history series; hover exposed an Oct 3 source value, and toggling the startup legend removed then restored its line without changing portfolio odds. Earlier sparse single-series states remain verified. |
| 6 | Collection rename, membership, safe deletion | PASS | Earlier hosted rename/membership/delete flows survived reload and kept member goals. |
| 7 | Photos-style selection | PASS | Earlier live desktop/mobile Select, count, cancel, move, disabled Share and archive confirmation. |
| 8 | Profile composition and editor | PASS | Earlier signed-in desktop/mobile edit and save/reload; no new Profile layout change in #21. |
| 9 | Private persistent profile photo | NOT VERIFIED | Local upload/reload/remove tests; actual owner-scoped production upload remains blocked by Chrome extension file access. |
| 10 | Behavioral radar | NOT VERIFIED | Unknown axes remain honest and area assignment persisted, but full behavioral demonstration and live measured radar remain absent. |
| 11 | GitHub discovery and real records | PASS | Earlier production `buildnorth` commit read and owner/repository selection; this does not prove the proposed LeetCode watch. |
| 12 | Notion discovery and content | PASS | Earlier real Oct 20 report fetched, normalized and source linked; it does not prove parent-child monitoring. |
| 13 | Automatic goal-aware relevance | NOT VERIFIED | #21 changed connected-source planning from HTTP 422 to a successful production response: Notion suggested for reading, GitHub left unranked. The picker exposes ten pages but no `Book Reports` parent; title match alone is not evidence. |
| 14 | Sync, deduplication and receipts | PASS | Earlier new GitHub/Notion ingestion repriced reading 10.6%→15.1%; repeat recorded zero new rows. Scheduled repeated Notion reads also recorded zero new rows. New-child publication is separate and unverified. |
| 15 | Durable async processing and latency | FAIL | Cron persists and processes approved watches, but cold `/health` took 22.16s and signed-in session hit the prior 12s false timeout. Authenticated p50/p95 and the ordinary-navigation target are unmet/unmeasured. #21 raises the session wait to 45s with honest slow-start copy, which is UX mitigation, not a server latency fix. |
| 16 | Fresh OAuth Pending→Connected | NOT VERIFIED | Polling contract tests exist; no fresh authorized OAuth flow was observed. |
| 17 | Minimal copy and styled controls everywhere | FAIL | Production source suggestion exposed `Type: threshold` and internal “goal contract” language; a follow-up branch edit removes those. Complete route-by-route visual/console acceptance remains absent. |
| 18 | Forecasting, What If, auth and evidence regression | NOT VERIFIED | Signed-in reading Change scenario persisted 13%→93% as a hypothetical result, while the goal card showed published 15.1%; the distinction needs review. Other families and all four modes were not rerun on this SHA. |
| 19 | Authenticated desktop/mobile production acceptance | NOT VERIFIED | Desktop Evidence and What If were inspected after #21. The Chrome viewport override remained 1440 CSS px, so a new production mobile inspection could not be claimed; earlier mobile screenshots do not cover all current flows. |

**Autonomous observability boundary.** Render Cron `crn-dbdob93rjlhs73e07dhg` runs every 15 minutes on 0.5c-512mb. At 20:45 UTC it scheduled two approved Notion resource watches, processed one durable job, read one record and added zero; at 22:00 UTC it did the same. The 23:30 run scheduled zero because nothing was due. The 19:45 scheduled run completed while the free web service was asleep, but no watch was due then. These observations verify independent scheduling, repeated authorized reads and deduplication. They **do not** verify a new parent child, edited/deleted/revoked resource, evidence extraction, forecast receipt or published history from automatic monitoring. The picker currently has ten authorized Notion pages and no `Book Reports` parent. The user has been asked to share the intended parent or name another authorized parent for the new-child test. No production report or goal was fabricated.

**New live collection check.** The `Career & company` collection (`c24e71e4-4707-4257-9675-ccf55dad66c3`) now contains three priced goals. Its desktop screenshot showed three colored histories, and a real legend checkbox removed/restored one line. The expanded calculation supplied the three source probabilities and the correct 87% rounded portfolio. The chart interaction changes only visibility, not membership or odds. This closes the earlier one-priced-member gap for outcomes 4 and 5 at desktop size; it does not establish a new authenticated 390px visual check.

**What If and course standing.** A signed-in reading Change run saved “2 books per week for the rest of 2026” with 13% scenario baseline, 93% hypothetical odds and +80.0 percentage points; it did not claim an identified causal effect or an estimated follow-through. Its live chart lacked an outcome distribution yet showed a stale prompt; #21 now labels scenario odds and absent ranges honestly. A further live reading Futures run returned three structural labels with no numerical weights; the backend correctly withheld shares, but the UI rendered dash-filled result cards. PR #22 now suppresses those cards and shows the backend's unpriced reason; deployed recheck is pending. Course standing passed deterministic/backend and mocked desktop/mobile tests, but no signed-in production course goal was identified for a real API/visual check. Neither scenario generated a published goal forecast history point.

**Performance and cost.** Before the lazy Composio change, one warm authenticated connected-source request took 8,680ms and saved recipes 9,085ms. After #16, three warm Evidence reloads showed connected-source requests of 141/122/195ms (median 141ms) and recipes 459/255/290ms (median 290ms). These small, non-matched samples do not establish p95. Production source planning before #21 returned 422 in 5,411–16,722ms; after #21 it returned a ranked Notion suggestion in the signed-in browser, but a timed matched sample remains. Notion resource discovery took 5,396ms in an earlier trace. The user approved Render Cron at the lowest suitable plan; the earlier billing page showed $0.00 accrued, $0.27 projected for October and $50 promotional credit, not a settled charge. The latest What If may use the previously approved BYOK budget; exact provider delta was not independently captured. No new infrastructure, production goals or synthetic evidence were added. No database migration was added in #21.

### 2026-10-24 continuation checkpoint

PR #22 passed CI and merged as `f12a153`. It removes internal Evidence copy, distinguishes the What If scenario baseline, and withholds dash-only Futures result cards when the backend has no valid weights. Signed-in browser acceptance of those deployed changes is **NOT VERIFIED** because the Chrome control connection stopped responding during the follow-up visit. No numerical result or forecast history was invented.

Open PR #23 (`841f12b`) changes the behavioral radar to default to Overall and select one measured area at a time. The backend always returns the person-wide series and only emits area series with sufficient comparable trials; specific coding, fitness, reading, sports, music, school and work domains are recognized without treating activity as follow-through. The Evidence UI now defaults to monitoring selected Notion pages, with a separate opt-in for accessible subpages. Sixteen backend trait tests, three radar component tests, two source-selection tests, Ruff and TypeScript checks passed locally. CI and real signed-in desktop/mobile interaction on this head are pending; outcomes 10, 13, 17 and 19 remain **NOT VERIFIED/FAIL** as in the matrix above. No migration or production data write was made.

The Cron evidence boundary is unchanged: real scheduled repeats prove authorized reads and deduplication, not a new source event through forecast publication. Existing-page monitoring can be tested without an authorized parent. The parent prerequisite applies solely to new-child discovery. The full What If mode matrix, new multi-domain goal creation, authenticated course-grade flow and production p50/p95 are still outstanding.
