# Pass 06 result — Personal agents on the existing MCP server

Date: 2026-10-23. Branch `feat/pass-06-personal-agents`, based on `origin/main` `4dcb523` (Lazy Composio navigation and bounded Notion discovery, #16). This branch was not merged and was not deployed. Production Render cron, credentials, database rows, and inference budgets were not modified.

The 2026-10-19 staging-packaging report is kept below. Its measured counts are historical and are not this run.

## Implemented

The existing `/mcp` OAuth server, Goal Architect, evidence ingestion, What If service, and published forecast receipts are unchanged in role. This pass adds reads and history selectors on that server.

- `get_forecast_readiness` — published or not, missing inputs, spec status. No invented probability.
- `list_milestones` — nodes stored on `forecast_spec.primitives`. Empty when the model has no milestone graph.
- `compare_forecasts` relatives: `this_month` (rolling 30 days), `since_start`, `largest_increase`, `largest_drop`, plus the previous `last_week`, `previous`, `before_evidence`, and `as_of`.
- Evidence listed between two receipts uses observation time. Ingestion time is reported separately and is never treated as the event time.
- If no receipt exists at the requested bound, the tool says so. It does not interpolate.
- Settings → Personal agents: ChatGPT and Grok connection steps, permission list from the server scopes, revoke behavior, and an explicit not-verified line for ChatGPT Chat, ChatGPT Work, Grok Bot, and in-host interactive charts.

Goal title, deadline, and success definition are not writable through MCP. Progress remains `submit_structured_evidence` / `submit_structured_rows` / `submit_table_text` / `submit_file_bytes` (40 KB decoded cap, no URL fetch). What If stays hypothetical.

## Reused

OAuth 2.1 + PKCE, scope gateway, owner checks, idempotent evidence, Goal Architect clarification/confirmation, Baseline reprice, What If, Odds Explorer MCP App `ui://playitout/odds-explorer`, and `get_odds_chart_image`.

## New MCP tools

`get_forecast_readiness`, `list_milestones`.

## Modified schemas

`compare_forecasts.relative` and `compare_scenarios.relative` patterns. `ForecastCompare` adds `delta_basis`, `evidence_changes`, and `extremum`.

## Security

Same scopes as before. New tools require `goals:read`. State-changing tools are unchanged. No new secret store. Production tokens were not minted from this session.

## Tests this run

| Suite | Result |
|---|---|
| `test_remote_mcp_temporal.py` + `test_remote_mcp_protocol.py` + `test_remote_mcp_pass05.py` | **32 passed** |
| Vitest `personalAgents.test.tsx` | **2 passed** |
| Production OAuth discovery | **PASS** (metadata 200, unauthenticated `/mcp` 401) |
| Production authenticated tools | **NOT TESTED** (would use the deployed server, not this branch, and was not authorized to write) |
| ChatGPT Chat / Work / Grok Bot | **NOT TESTED** |
| Signed-in Settings page | **NOT TESTED** — `localhost:5173/settings` showed Clerk sign-in; `localhost:5174/settings` rendered the shell and “Personal agent settings are unavailable” because `/api/v1/mcp/status` returned authentication required |

`uv run pytest` (the console script) failed to import `pydantic_settings` in this environment. `uv run python -m pytest` succeeded.

## Client capability

See `docs/final/reports/CLIENT_CAPABILITY_MATRIX.md`. Local reference-client cells that this run executed are PASS. ChatGPT and Grok cells are NOT TESTED. They are not inferred from unit tests.

## Chart support

Interactive Odds Explorer remains an MCP App on the same OAuth connection. Static PNG remains `get_odds_chart_image`. Neither was exercised inside ChatGPT or Grok in this run.

## Unsupported

- Rewriting goal title, deadline, or success definition through an agent.
- Marking agent-submitted evidence independently verified.
- Fetching private-network URLs.
- Publishing a public ChatGPT plugin.
- Claiming ChatGPT or Grok host UI from the SDK.

## Integration dependencies

None on the open remediation PR #17 or on the stashed Codex working tree (`feat/playitout-next-pass`, stash `preserve Codex WIP on feat/playitout-next-pass before pass-06`). This branch does not contain that course-grade work. Do not merge until that remediation is reconciled if both touch the same forecast or What If files.

## Commits and PR

- `6438320` — Let personal agents read forecast readiness and published odds history.
- Draft PR: https://github.com/MrSujalThapa/buildnorth/pull/18
- Not merged. Not deployed.

---

# Earlier run — 2026-10-19 private staging packaging

Date: 2026-10-19 (Toronto). Pass 06 only. No Pass 07/08/09 work. No marketplace, ML expansion, Jev, Era, public plugin listing, or ChatGPT Sites app.

**Verdict: BLOCKED (operator provisioning)**

Local regression, isolated Postgres integration, and mocked-auth browser checks **PASS**. Private HTTPS staging, live Clerk Google identities, ChatGPT Plus, Grok Bot, Gmail handoff, and dashboard sync against hosted data are **NOT VERIFIED**. No staging URLs, credentials, or successful cloud deploys are invented in this report.

The Cursor-linked Supabase project `https://klcqvxhemrirjixherkl.supabase.co` answers the management API, but SQL (`list_tables`, `list_migrations`, `execute_sql`) times out. That is the typical paused free-tier compute state. Local `127.0.0.1:54322` was not copied, reset, or pointed at as staging.

---

## What this pass did autonomously

1. Added a single-worker Docker API image, Render Blueprint, Vercel SPA config, and `.env.staging.example` so staging can be created from existing source and migrations `0001–0015`.
2. Made `scripts/db_migrate.py` record applied files in `schema_migrations` so container restarts do not re-run `CREATE TABLE`.
3. Raised OAuth DCR `redirect_uris` cap from 5 to 16 and accepted the Cursor native `cursor://` callback used by Grok Bot DCR. HTTPS-only (plus loopback http) validation is unchanged; `javascript:` / `data:` / `file:` still fail.
4. Empty `PM_CORS_ORIGIN_REGEX` now disables the localhost regex so staging CORS is the explicit origin list.
5. Documented the exact operator dashboard steps required before live ChatGPT/Grok tests can start.

No new forecasting engine, no UI redesign, no duplicate data layer, no test-auth weakening.

## Files changed

### Added

- `Dockerfile` — Python 3.12, `uv sync --frozen --no-dev`, migrate then one `python -m personal_markets` process
- `.dockerignore`
- `render.yaml` — one Web Service, `/health`, secrets `sync: false`
- `vercel.json` — `apps/web/dist` SPA
- `.env.staging.example` — names and placeholders only
- `docs/final/reports/PASS_06_RESULT.md` (this file)
- `docs/final/reports/CLIENT_CAPABILITY_MATRIX.md`

### Modified

- `apps/api/src/personal_markets/remote_mcp/oauth.py` — `_MAX_REDIRECT_URIS = 16`, `_NATIVE_APP_SCHEMES = {"cursor"}`
- `apps/api/src/personal_markets/__main__.py` — `HOST` / `PORT` from the environment (Render injects `PORT`)
- `apps/api/src/personal_markets/core/config.py` — blank CORS regex → `None`
- `apps/api/tests/test_remote_mcp_oauth.py` — ChatGPT-style URI bundle, cap, Cursor native callback
- `apps/api/tests/test_api.py` — empty CORS regex
- `scripts/db_migrate.py` — application tracking + legacy bootstrap when `goals` already exists
- `.env.example` — `PM_PUBLIC_API_URL`, `PM_PUBLIC_WEB_URL`, `VITE_API_BASE_URL`
- `.gitignore` — `!.env.staging.example`
- `docs/IMPROVEMENT_CHANGELOG.md`

### Migrations

None numbered. Still `0001–0015`. Operational table `schema_migrations` is created by the migrate script, not a product migration. Local development database `postgres` recorded the 15 existing files and skipped re-apply. Isolated `playitout_pass06_test` applied all 15 from empty.

## Public contracts

Unchanged tool surface from Pass 05 (19 MCP tools). Staging must advertise:

- Resource: `{PM_PUBLIC_API_URL}/mcp`
- OAuth discovery: `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource/mcp`
- PKCE S256, DCR, revocation
- Caps: hosted inference `$25` global / `$2` per user; MCP file 40 KB; JSON 64 KB

`PM_PUBLIC_API_URL` / `PM_PUBLIC_WEB_URL` remain loopback until the operator supplies real HTTPS origins.

## Security / cost

| Control | Staging intent | Status |
|---|---|---|
| `PM_ENVIRONMENT=staging` | Required | Configured in `render.yaml`; not live |
| `PM_TEST_AUTH_SECRET` empty | Fail-closed if set on public HTTPS | Code already enforced; not live |
| `PM_DEV_BOOTSTRAP_TEST_USERS=false` | Fail-closed | Same |
| `VITE_AUTH_BYPASS=false` | Frontend | Template only |
| `/health/details` | Hidden when public HTTPS | Untouched; not live |
| One API worker | `numInstances: 1`, no `--workers` | Image built for this; not live |
| `PM_TRUST_FORWARDED_HEADERS` | Leave `false` until the Render peer IP is known | Template |
| Hosted caps `$25` / `$2` | Unchanged | Template |
| Eval scripts | Not wired into the app; do not run them on staging | Architecture check passed |
| Local DB | Not uploaded or reset | Preserved (`postgres`, `playitout_e2e`, etc.) |

## Tests

Identities in these runs are **backend test principals** unless noted. They are **not** Clerk Google sessions and **not** ChatGPT/Grok.

| Suite | Result | Notes |
|---|---|---|
| Backend pytest (no `PM_TEST_DATABASE_URL`) | **502 passed, 4 skipped** | Four skips are isolated Postgres tests against default `playitout_phase0_test` |
| Isolated Postgres `playitout_pass06_test` + `-m integration` | **10 passed** | Fresh DB, migrations `0001–0015`, then skip on re-run |
| Vitest | **33 passed** | |
| `tsc -b` | clean | |
| Production Vite build | clean | `apps/web/dist` |
| `check:architecture` | passed | |
| `check:migrations` | passed (15 files) | |
| Playwright Odds Explorer | **2/2** | Desktop + mobile-chromium, `VITE_AUTH_BYPASS`, mocked API |
| Ruff on Pass 06 Python files | clean | |
| Docker image `playitout-staging-api:pass06` | **built locally** | `docker build` succeeded; image not pushed and not deployed |
| Live Clerk Google A/B/C | **NOT VERIFIED** | Needs hosted web origin |
| ChatGPT Plus Chat / Work | **NOT VERIFIED** | Needs public HTTPS `/mcp` |
| Grok Bot | **NOT VERIFIED** | Same |
| Gmail → PlayItOut | **NOT VERIFIED** | Same |
| Hosted dashboard sync | **NOT VERIFIED** | Same |

No paid hosted-inference evaluation scripts were run.

## Browser / consumer clients

- Local Odds Explorer (mocked auth): PASS (Playwright).
- Hosted dashboard with Google sign-in: NOT VERIFIED.
- ChatGPT regular Chat: NOT VERIFIED.
- ChatGPT Work: NOT VERIFIED.
- Grok Bot / grok.com connectors: NOT VERIFIED.
- Hosted reference MCP SDK client: NOT VERIFIED.

OpenAI’s current plugin docs say ChatGPT can add a custom MCP server from Plugins and that write tools exist, while some help-center copy still describes full MCP as a Business/Enterprise workspace feature. Pass 06 will record whichever behavior the Plus account actually exhibits. It will not be treated as success from documentation.

## Blockers requiring user action

Stop here. The next actions cannot be completed from this repository without your dashboards.

Reply in chat with **only**:

1. Supabase project ref (or “unpaused `klcqvxhemrirjixherkl`”).
2. Render API HTTPS origin (no path).
3. Vercel web HTTPS origin (no path).
4. Confirmation that Clerk allowed origins / azp include that web origin.

Do **not** paste database passwords, Clerk secrets, Spur keys, or connection strings into chat. Put those only in Render / Vercel environment variables.

### 1. Hosted Postgres (do this first)

Local `127.0.0.1:54322` stays as development. Staging needs a **distinct** hosted project.

**Option A — unpause the already-linked project** (only if it is empty / dedicated for staging, not a copy of local data):

1. Open [https://supabase.com/dashboard](https://supabase.com/dashboard).
2. Select project `klcqvxhemrirjixherkl`.
3. If the banner says the project is paused, restore/unpause it and wait until the SQL editor runs `select 1`.
4. Project Settings → Database → connection string.
5. Use **session mode, port 5432** (direct `db.<ref>.supabase.co:5432` or session pooler on `5432`). Append `?sslmode=require`.
6. Do **not** use transaction-mode port `6543`. LangGraph’s Postgres checkpointer and asyncpg need a session.

**Option B — new project** (preferred if A has leftover data you do not want):

1. New project named `playitout-staging`.
2. Region close to Render.
3. Same session-mode URI as above.
4. Leave the database empty. Render’s container will apply `0001–0015` on first start.

Paste the URI into Render as `PM_DATABASE_URL` only.

### 2. Render API (one worker, HTTPS)

1. Open [https://dashboard.render.com](https://dashboard.render.com) and sign in.
2. New → Blueprint, connect GitHub `MrSujalThapa/buildnorth`, use `render.yaml`.
   Alternative: New → Web Service → Docker, Dockerfile path `./Dockerfile`, instance count **1**, health check `/health`.
3. Set non-secret values from `render.yaml`. Then in Environment, set the `sync: false` keys using `.env.staging.example` as the name list:
   - `PM_DATABASE_URL` (session-mode URI from step 1)
   - `PM_CLERK_JWKS_URL` and `PM_CLERK_ISSUER` from Clerk → API keys (same instance as local is fine)
   - `PM_ADMIN_EMAILS` as JSON with your Google admin address
   - `PM_SPUR_API_KEY` / `PM_BYOK_ENCRYPTION_KEYS` (new staging keys; do not reuse local BYOK keys if the DB is distinct)
   - Leave `PM_TEST_AUTH_SECRET` empty and `PM_DEV_BOOTSTRAP_TEST_USERS=false`
4. First deploy will assign `https://<name>.onrender.com`. Copy that origin.
5. Set `PM_PUBLIC_API_URL` to that origin (no trailing slash, no `/mcp`).
6. After Vercel exists, set `PM_PUBLIC_WEB_URL`, `PM_CORS_ORIGINS`, and `PM_CLERK_AUTHORIZED_PARTIES` to the Vercel origin and **redeploy** the API. OAuth issuer and CORS are wrong until this second deploy.

Confirm `GET https://<api>/health` returns `{"status":"ok",...}` with no database field. `GET https://<api>/health/details` must be 404.

### 3. Vercel frontend

`VITE_*` variables are compile-time. Set them **before** the production build.

1. Open [https://vercel.com/new](https://vercel.com/new) and import `MrSujalThapa/buildnorth`.
2. Root Directory: repository root (empty). `vercel.json` already sets install/build/output.
3. Environment variables for Production:
   - `VITE_API_BASE_URL` = the Render origin from step 2
   - `VITE_CLERK_PUBLISHABLE_KEY` = Clerk publishable key
   - `VITE_AUTH_BYPASS=false`
   - `VITE_TEST_AUTH_TOKEN` empty
   - `VITE_DEV_DEMO_SIMULATIONS=false`
4. Deploy. Copy `https://<name>.vercel.app` (or the assigned domain).
5. If you change `VITE_API_BASE_URL` later, Redeploy with rebuild.

### 4. Clerk Google + origins

1. Clerk Dashboard → the instance already used locally.
2. User & Authentication → SSO connections → Google: enabled.
3. Configure → Domains / allowed origins: add the Vercel HTTPS origin.
4. Authorized parties (`azp`): add the same origin (must match `PM_CLERK_AUTHORIZED_PARTIES`).
5. Redirect URLs: add `https://<vercel>/*`.
6. Do not turn on test-token or skip-invitation features.

After the API second deploy, sign-in with Google as account A (admin email). `/api/v1/me` should show `invited: true`. Then we continue A/B/C, MCP, ChatGPT, and Grok.

### 5. After URLs exist (do not do this yet)

Exact ChatGPT / Grok clicks will be executed in the continuation, not assumed here:

- ChatGPT: [chatgpt.com](https://chatgpt.com) → Plugins → `+` → Add custom MCP server → Server URL `{PM_PUBLIC_API_URL}/mcp` → OAuth → Create as a plugin. **Do not publish.** Test regular Chat separately from Work (`@plugin`).
- Grok web: [grok.com/connectors](https://grok.com/connectors) → New Connector → Custom → same `/mcp` URL.
- Grok Bot: Settings → Plugins → custom MCP, same URL, OAuth. If DCR sends `cursor://…`, that URI is now accepted.

## Outstanding risks

- ChatGPT Plus may still restrict write tools even when the Add-server UI is visible. Record actual behavior.
- MCP Apps interactive Odds Explorer is not guaranteed inside regular ChatGPT or Grok. PNG + dashboard remain the fallback.
- Gmail → PlayItOut is a host transfer, not a PlayItOut Gmail grant. Binary attachments may fail the 40 KB / host limit; structured-row handoff is the fallback.
- Render X-Forwarded-For is not trusted yet; rate limits may collapse to the proxy IP. Acceptable for invite-only staging.
- `schema_migrations` on local `postgres` is new operational metadata only.

## Rollback

- Do not deploy: leave local `.env` pointed at `127.0.0.1:54322`. Local product is unchanged aside from OAuth URI-cap, CORS empty-regex, PORT/HOST, and migrate tracking.
- If a half-created Render/Vercel/Supabase project exists after you start: delete the Render service, Vercel project, and unused Supabase project. Do not delete the local CLI stack.
- Revert this pass’s git files if you want the pre-Pass-06 tree.

## Next instruction

**Do not start Pass 07.** Provision the four operator steps above, reply with the three HTTPS/project values (no secrets), then continue Pass 06 live acceptance: Clerk A/B/C, ChatGPT Chat vs Work, Grok Bot, Gmail structured handoff, dashboard isolation, revocation.

---

**PASS / PARTIAL / BLOCKED:** **BLOCKED**
