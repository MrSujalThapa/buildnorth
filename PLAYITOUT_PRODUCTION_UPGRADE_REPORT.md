# PlayItOut production upgrade report

Date: 2026-10-19  
Working branch: `main`  
Live frontend: https://buildnorth-delta.vercel.app  
Live API: https://playitout-api.onrender.com  

This report distinguishes **local mocked tests** from **real deployed browser verification**. Compiling or unit-testing is not treated as production-ready proof.

Paid inference this session: **$0.00** so far. The $0.10 verification ceiling is authorized; a live Spur/Anthropic completion will be issued against the deployed API after this SHA is live, not against local `.env`.

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
| 1 Inference (Spur, BYOK, discovery) | Implemented | PASS | NOT TESTED (no paid call yet) |
| 2 Latency (RQ, dashboard, DB pool, plugin cache, async agents) | Implemented | PASS targeted | PARTIAL (Render cold start observed) |
| 3 Composio / Plugins | Implemented catalog/error path | PASS mocked | NOT TESTED |
| 4 Settings privacy + Hosted/BYOK split | Implemented | PASS | NOT TESTED this session |
| 5 Create menu, select, archive | Implemented | PASS | NOT TESTED |
| 6 Collections + progress | Implemented | PASS | Local 0016 applied; hosted pending Render migrate |
| 7 Profile + radar | Implemented | PASS | Local 0016 applied; hosted pending Render migrate |
| 8 Withheld + evidence UX | Implemented | PASS classifier | NOT TESTED in deployed UI |
| 9 Deploy + this report | Report updated | Targeted suite PASS | `9ffa538` pushed; follow-up SHA in flight |

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
9. **Render cold start.** Unauthenticated `/health` returned the Render “Application loading” interstitial rather than JSON. This is a primary live latency source, separate from app code.

---

## 4. Commit SHAs

- Previous `HEAD`: `386dfc4`
- `a36af19` — *Ship judge-facing product upgrades without inventing odds or hosted OpenAI fallback.*
- `e3ebeaa` — *Record the upgrade commit SHA in the production report.*
- `9ffa538` — *Refuse silent local Postgres when migrating PlayItOut schema.* Pushed to `origin/main`.
- Follow-up on `main`: async agent start (`Prefer: respond-async`), Profile lint, Hosted/BYOK picker controls. SHA recorded after commit.

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

---

## 7. Screenshots / real UI tests

- Local Vitest: `apps/web/src/App.test.tsx` 6/6 PASS (create menu, markets shell).
- Playwright pass06 mocks updated for the Create split control. Fixture-backed only.
- Live deployed UI for this SHA: **NOT TESTED**. Render `/health` was still in cold-start interstitial when probed.

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
| Dashboard batch | One round-trip for markets | NOT TESTED |
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

1. **Hosted 0016** is applied only by Render `db_migrate.py` on boot. Local 0016 is already applied and must not be treated as hosted proof.
2. **Deploy the follow-up SHA** to Render and Vercel (`9ffa538` is on `origin/main`; async/lint follow-up is next).
3. **Live Spur and Anthropic completions** remain within the $0.10 ceiling after the API is serving this code. Spur catalog estimates are still unverified invoices.
4. **Confirm Composio** on Render only if Plugins is still empty after deploy. Do not reprint secrets.
5. **Warm the Render service** before judging; cold start dominates first-hit latency.
6. **Async agents** now return a running snapshot when the client sends `Prefer: respond-async`. Crash mid-run can leave `status=running` on a single Render worker until retry.
7. **Featured plugin logos / OAuth round-trip** need a real Composio account connection after deploy.
8. Evidence upload mapping still uses native `<select>` for CSV columns; Hosted/BYOK and Markets move-to now use PlayItOut buttons.

---

## 15. Judge-readiness assessment

**Not production-ready** as a deployed judge experience for this SHA.

The product code now covers the requested judge loop: Spur-hosted mode in software, one-step BYOK, model discovery, cached navigation, honest plugin errors, Hosted vs BYOK settings, goal archive, collections with honest progress, a private profile radar, and withheld-forecast explanation. That is **local/unit evidence**.

A judge hitting the current Vercel/Render pair has **not** been shown this SHA. Live Spur inference, live Anthropic usage (beyond prior key validation), live Composio catalog/OAuth, migration 0016, and post-deploy performance numbers remain open.

### Requirement matrix

| Requirement | Status |
| --- | --- |
| 1A.1 Deployed API recognizes Spur | NOT TESTED (health cold start; env claimed configured) |
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
| 2A Measure first | PARTIAL — cold start documented; warm p50/p95 missing |
| 2B React Query SWR | PASS code |
| 2C Dashboard batch + plugin cache | PASS unit |
| 2D DB/engine | PASS code; live query plans NOT TESTED |
| 2E Async agents | PASS code + unit (`Prefer: respond-async`); live NOT TESTED |
| 3A Empty catalog diagnosis | PASS code |
| 3B Judge OAuth | NOT TESTED |
| 3C Plugin browsing polish | PARTIAL |
| 4A Hide global budget | PASS unit |
| 4B Split Hosted/BYOK UI | PASS mocked e2e |
| 4C Consistent primitives | PARTIAL |
| 5A Create menu | PASS unit |
| 5B Select mode | PASS code |
| 5C Safe deletion | PASS unit (soft archive) |
| 6A Collection model | PASS unit |
| 6B Collection graphs | PASS code |
| 6C Progress ≠ probability | PASS unit |
| 7A Profile | PASS unit |
| 7B Aggregated radar | PASS code |
| 8A Withheld explanation | PASS unit + persist |
| 8B Evidence form | PASS code |
| 9 Tests / typecheck | PASS targeted |
| Hosted Supabase is the production database | PASS (intended: Render `PM_DATABASE_URL`; local `.env` still loopback) |
| Inspect migrations before apply | PASS local dry-run (0016 applied, none pending). Hosted inspected only via Render migrate-on-boot, not MCP. |
| `supabase db push` not used | PASS |
| 0016 applied on local DB | PASS (`127.0.0.1:54322`, `collections_table True`) |
| 0016 applied on hosted DB | NOT TESTED until Render boots this SHA and collections/profile are read with a real session |
| Render reads/writes hosted DB | PARTIAL — `/health` 200, `/api/v1/goals` 401, `/health/details` 404 by design. Row-level hosted proof after migrate-on-boot. |
| 9 Live deploy of this SHA | `9ffa538` pushed; follow-up SHA not yet serving |
| 9 Two-user live isolation | NOT TESTED |
| 9 Mobile/desktop live | NOT TESTED this SHA |

**Definition of done:** not met for the live judge URL until deploy, migration, and a bounded live inference/plugin pass succeed.
