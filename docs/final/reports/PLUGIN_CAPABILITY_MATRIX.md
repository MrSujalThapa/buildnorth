# Plugin Capability Matrix

**Audit date:** 2026-10-23  
**Code:** `origin/main` @ `f12a153`  
**Rule:** A logo, static `PLUGIN_DEFINITIONS` entry, or Composio toolkit slug is **not** evidence of Evidence-ready support.

Verification legend:

| Label | Meaning |
| --- | --- |
| **VERIFIED LIVE** | Exercised against a real connected account in production notes |
| **VERIFIED AUTHENTICATED STAGING** | Authenticated non-prod (not claimed here) |
| **TESTED WITH MOCKS** | Unit/contract/Playwright mocks |
| **IMPLEMENTED BUT NOT TESTED** | Code present; no adequate test found |
| **NOT IMPLEMENTED** | No meaningful adapter depth |
| **BLOCKED BY EXTERNAL PERMISSION** | Live attempt blocked by share/OAuth scope |

---

## Platform spine (all Composio toolkits)

| Capability | Status | Notes / evidence |
| --- | --- | --- |
| OAuth initiate | **GENERIC** / **TESTED WITH MOCKS**; live GitHub+Notion connect noted | `initiate_connection`; fresh Pending→Connected for all toolkits **NOT VERIFIED** |
| Tool list + read policy | **GENERIC** / **TESTED WITH MOCKS** | `list_tools`, `MCPReadPolicy` |
| Resource discovery | **PARTIAL** | Preferred tools only for github/notion |
| Recipe save/execute | **PARTIAL** | Strong allowlists for github/notion; others weak |
| Watches + Cron enqueue | **GENERIC** / watches **TESTED WITH MOCKS**; Cron runner **IMPLEMENTED BUT NOT TESTED** | `source_watches`, `watch_runner` |
| Dedupe + owner scope | **GENERIC** / **TESTED WITH MOCKS** + live zero-new | fingerprints, `0019` ownership |
| Evidence → forecast | **GENERIC** once `new_records` | Manual **VERIFIED LIVE**; Cron new-delta **NOT VERIFIED** |

---

## Provider matrix

### Notion

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | Composio toolkit `notion` | Live connect / picker **VERIFIED LIVE** |
| Resource discovery | `NOTION_SEARCH_NOTION_PAGE`; ≤5 cursor pages / ≤100 results; drop untitled | Pagination **TESTED WITH MOCKS**; live ~10 pages **VERIFIED LIVE**; complete workspace list **NOT VERIFIED** |
| Read capabilities (sync) | Allowlist: `NOTION_GET_PAGE_MARKDOWN`, `NOTION_FETCH_ALL_BLOCK_CONTENTS`, `NOTION_FETCH_BLOCK_CONTENTS` | **TESTED WITH MOCKS**; live markdown **VERIFIED LIVE** |
| Evidence types | Document body; fingerprint page id + markdown; no structured “books finished” metric | Content ingest **VERIFIED LIVE**; semantic book count **NOT IMPLEMENTED** |
| Goal matching | Token ranker; Book Reports title promotes Notion in tests | Ranker **TESTED WITH MOCKS**; live parent missing **BLOCKED BY EXTERNAL PERMISSION** |
| Sync | Goal recipes; manual Sync jobs | Manual **VERIFIED LIVE** |
| Incremental | Content hash; generic `since` may be ignored by Notion tools | Unchanged dedupe **VERIFIED LIVE** (manual + Cron) |
| Watches | UI forces `scope=parent`; API allows `resource` | Controls **TESTED WITH MOCKS**; live “Monitoring 2 of 2” **VERIFIED LIVE** |
| New-child discovery | Parent BFS via `NOTION_FETCH_BLOCK_CONTENTS` | **TESTED WITH MOCKS**; live **BLOCKED BY EXTERNAL PERMISSION** (no Book Reports parent) |
| Database monitoring | Outstanding per changelog | **NOT IMPLEMENTED** |
| Hardcoding | Preferred search tool; allowlists; date mentions; Notion-only descendants | Code |
| User config | Share pages with integration; select pages; Save; optional Monitor + Cron | — |
| Blockers | Missing shared parent; bounded search; forced parent UX | — |

### GitHub

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | Composio `github`; legacy public Events API separate (`integrations/github.py`) | ACTIVE reconcile **VERIFIED LIVE** |
| Resource discovery | `GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER` | Live repos **VERIFIED LIVE**; discovery **TESTED WITH MOCKS** |
| Read capabilities | Commits / PRs / issues allowlist in `_supported_goal_step` | Recipe selection **TESTED WITH MOCKS**; commits sync **VERIFIED LIVE** |
| Evidence types | `repository_activity` / PR / issue events; SHA fingerprint | Normalizer **TESTED WITH MOCKS**; live commits **VERIFIED LIVE** |
| Goal matching | Ranker + activity checkboxes | UI + tests |
| Sync / watch | `scope=resource` | Manual **VERIFIED LIVE**; Cron watch **NOT VERIFIED** |
| Incremental | SHA dedupe; `since` on sync; public Events cursor on legacy path | Repeat sync `records_new=0` **VERIFIED LIVE** |
| Hardcoding | Preferred list tool; activity map; NeetCode withhold | `withhold_commit_only_solution_claims` **TESTED WITH MOCKS** |
| User config | Connect; pick repo; pick activity types; Save; optional Watch | — |
| Blockers | Commit ≠ accepted solution still a semantic risk if policy bypassed | — |

### Gmail

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | Composio OAuth possible | Auth launcher noted; Evidence-ready **NOT VERIFIED** |
| Resource discovery | No preferred tool; heuristic `list_threads`/`list_labels` if present else `[]` | **NOT IMPLEMENTED** at Evidence-ready depth |
| Normalizer | Generic stub | **NOT IMPLEMENTED** |
| Live ingest → forecast | — | **NOT IMPLEMENTED** / **NOT VERIFIED** |

### Google Calendar

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | Composio OAuth possible | Auth notes only |
| Resource discovery | Heuristic `list_calendars` | **NOT IMPLEMENTED** Evidence-ready |
| Normalizer / goal proof | Generic | **NOT IMPLEMENTED** |
| Live ingest | — | **NOT VERIFIED** |

### Google Drive

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | Catalog + Composio | **NOT VERIFIED** Evidence-ready |
| Discovery | Heuristic `list_files`/`list_folders` | **NOT IMPLEMENTED** Evidence-ready |
| Live ingest | — | **NOT VERIFIED** |

### Google Sheets

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | Catalog + Composio | **NOT VERIFIED** Evidence-ready |
| Discovery | Heuristic `list_spreadsheets`/`list_sheets` | **NOT IMPLEMENTED** Evidence-ready |
| Live ingest | — | **NOT VERIFIED** |

### Strava

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | Static definition `strava.activities.read` | Catalog only |
| Discovery / normalize | No preferred tools / no activity extractor | **NOT IMPLEMENTED** |
| Live ingest | — | **NOT VERIFIED** |

### Slack / Figma

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | Catalog stubs + possible Composio auth | Auth launcher mentions Slack; Evidence-ready **NOT VERIFIED** |
| Discovery / normalize | Heuristic / generic | **NOT IMPLEMENTED** |
| Live ingest | — | **NOT VERIFIED** |

### Manual / CSV

| Dimension | Finding | Verification |
| --- | --- | --- |
| Connection | In-app | N/A |
| Evidence | Manual entries / uploads | Manual reprice **TESTED WITH MOCKS** / API tests |

---

## Static catalog vs live gateway

`plugins.py` `PLUGIN_DEFINITIONS` lists: manual, csv, github, gmail, calendar, drive, strava, notion, slack, sheets, figma.

- `provider_type`: github `"direct"`, others `"future_gateway"` — marketing-era label; live path is Composio for managed plugins.
- `DirectIntegrationGateway.connection_status`: non-GitHub → `UNAVAILABLE` (not the live Composio path).
- Live catalog also merges remote Composio toolkit search — **connectable ≠ Evidence-ready**.

`ReadCapabilityPolicy._allowed_operations` allowlists marketing ops (`gmail.messages.selected.read`, etc.). Live capabilities are largely `plugin.dynamic.<TOOL>.read` from Composio tool names. The static allowlist is **not** proof those providers work.

---

## Ten seamless-workflow steps × provider

| Step | Notion | GitHub | Gmail | Calendar | Drive | Sheets | Strava |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 OAuth | Live | Live | Partial | Partial | Partial | Partial | Catalog |
| 2 Discover resources | Live bounded | Live | Empty/heuristic | Heuristic | Heuristic | Heuristic | None |
| 3 List read tools | Generic | Generic | Generic | Generic | Generic | Generic | Generic |
| 4 Rank for goal | Partial | Partial | Weak | Weak | Weak | Weak | Weak |
| 5 Valid recipe | Allowlisted | Allowlisted | Weak True | Weak | Weak | Weak | Weak |
| 6 Fetch meaning | Page body | Commits/PR/issue | No | No | No | No | No |
| 7 Normalize | Hash doc | Events+SHA | Stub | Stub | Stub | Stub | Stub |
| 8 Proves progress | LLM | LLM + withhold | No | No | No | No | No |
| 9 Auto monitor | Poll; parent blocked | Code yes; Cron NV | No | No | No | No | No |
| 10 Forecast update | Manual yes; Cron NV | Manual yes; Cron NV | No | No | No | No | No |

NV = not verified.

---

## Test index (selected)

| Area | Tests |
| --- | --- |
| MCP connect/discover/dedupe | `test_mcp_integration.py` (`test_managed_connect_discover_sync_and_dedupe`, Notion/GitHub normalize, picker pagination) |
| Notion scope | `test_notion_scope.py`, `test_source_watches.py::test_parent_watch_*` |
| Planner / recipes | `test_source_planner.py` |
| Jobs / Cron claim split | `test_goal_sync_jobs.py`, `test_goal_sync_jobs_postgres.py` |
| GitHub solution policy | `test_github_solution_policy.py` |
| Watch UI | `apps/web/e2e/behavior_resources.spec.ts` (mocked) |
| Plugins E2E | `apps/web/e2e/plugins.spec.ts` |

---

## Honest “what works today”

| Works now | Does not work as advertised |
| --- | --- |
| Connect Notion + GitHub via Composio | Gmail/Calendar/Drive/Sheets/Strava as evidence sources |
| Pick shared Notion pages / GitHub repos | Full Notion hierarchy / databases / unshared parents |
| Manual sync → dedupe → evidence → forecast (Notion+GitHub) | Cron → new evidence → forecast → history |
| Cron poll unchanged Notion pages | New-child Book Reports discovery |
| Pause/Stop watches in UI (flag on) | Seamless one-click Connect→monitor for arbitrary Composio apps |
