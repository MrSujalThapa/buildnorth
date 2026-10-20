# PlayItOut production upgrade report

Date: 2026-10-19  
Working branch: `main`  
Live frontend: https://buildnorth-delta.vercel.app  
Live API: https://playitout-api.onrender.com  

This report distinguishes **local mocked tests** from **real deployed browser verification**. Compiling or unit-testing is not treated as production-ready proof.

The earlier sections below record the pre-sign-in state. The dated acceptance addendum at the end supersedes their live-status and blocker statements. No additional paid inference was deliberately initiated in the remediation pass; the preexisting BYOK ledger could not be used to isolate a per-pass charge.

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
