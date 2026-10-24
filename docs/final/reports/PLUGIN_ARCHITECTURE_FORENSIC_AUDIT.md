# Plugin Architecture Forensic Audit

**Audit date:** 2026-10-23  
**Code under review:** `origin/main` @ `f12a153` (“Refine source copy and record remediation acceptance (#22)”)  
**Inspection workspace:** `C:\Users\sujal\hackathons\buildnorth-audit` (detached worktree; primary Codex workspace left untouched)  
**Draft PRs reviewed but not treated as production:** #18, #19, #20 (draft), #17 (open, non-draft profile work) — **not merged for this audit**  
**Method:** Read-only code inspection, test inventory, and comparison against `docs/IMPROVEMENT_CHANGELOG.md` production notes. No production writes, no paid inference, no OAuth mutation, no Cron changes.

---

## Executive assessment

**PlayItOut does not yet have a scalable, low-friction plugin platform that can discover, understand, and monitor evidence across many external applications without substantial custom work.**

What exists today is a **credible generic spine** (Composio OAuth → tool listing → recipe execute → raw dedupe → evidence workflow → forecast publish) with **deep, provider-specific depth for two toolkits: GitHub and Notion**. The catalog advertises Gmail, Calendar, Drive, Sheets, Strava, Slack, and Figma. Those entries are mostly **catalog + allowlist stubs**. A tool appearing in Composio’s catalog does **not** mean PlayItOut can discover its resources, choose a correct read tool, normalize meaningful events, or prove goal progress.

The intended product loop:

> Connect → automatically discover relevant resources → user approves once → background monitoring → evidence → forecast

is **partially real** for GitHub and Notion **manual** sync, and **partially real** for Cron **poll + dedupe of unchanged Notion pages**. It is **not** proven for Cron → new evidence → forecast → published history. It is **not** real for arbitrary Composio integrations.

**Unambiguous answer:** the system is a **managed-gateway framework with two working adapters**, not a finished multi-provider evidence platform.

---

## Architecture diagram (actual path)

```text
[Plugins UI]
  POST /api/v1/plugins/{id}/connect
    → UnifiedIntegrationGateway / IntegrationGatewayService.connect_managed
      → ComposioIntegrationGateway.ensure_auth_config
      → ComposioIntegrationGateway.initiate_connection
      → pending_auth + OAuth redirect (Composio)

  reconcile ACTIVE accounts
    → list_tools → MCPReadPolicy.classify_tool
    → persist ReadCapabilityRecord as plugin.dynamic.<TOOL>.read

[Goal Evidence UI]
  GET resources / SourcePlannerService.plan
    → ComposioIntegrationGateway.list_resources
         preferred tools: github | notion only
         else heuristic list_* tool name match or []
    → resource_ranker.rank_resources (token overlap; optional LLM if disconnected)

  Save recipe
    → SourcePlannerService.save_recipe / build_recipe_steps
         GitHub/Notion tool allowlists + required resource_ids
         other plugins: first matching list* capability, return True

  Monitor (VITE_BACKGROUND_MONITORING)
    → source_watches.save
         Notion UI always scope="parent"
         other plugins scope="resource"

[Manual Sync or Render Cron]
  watch_runner.run_once  OR  web GoalSyncJob claim(include_watches=False)
    → SourceWatchStore.enqueue_due (Cron only after #14)
    → execute_goal_sync_job
      → GoalSyncService.sync_goal_sources
           intersect active watch URIs ∩ recipe steps
           [Notion parent] list_descendants → temporary child steps
           gateway.sync → ComposioTransport.call_tool → execute_tool
           normalize_tool_result → RawSourceRecord (owner-scoped fingerprint)
           if new_records:
             AgentWorkflow.start(kind="add_evidence", mcp_records=...)
               → evidence agent normalize/validate
               → commit_evidence → compute_forecast → publish
           else:
             status=no_new_records  (no inference, no history write)
```

### Concrete entry points

| Stage | File | Symbol |
| --- | --- | --- |
| OAuth | `integrations/composio_gateway.py` | `initiate_connection`, `ensure_auth_config` |
| Tool discovery | `composio_gateway.py` / `mcp_service.py` / `mcp_policy.py` | `list_tools`, `_discover_and_persist`, `MCPReadPolicy.classify_tool` |
| Resource discovery | `composio_gateway.py` | `list_resources`, `list_notion_child_pages` |
| Ranking | `integrations/resource_ranker.py` | `rank_resources`, `score_resource` |
| Source plan / recipe | `agents/source_planner_service.py` | `plan`, `save_recipe`, `_select_capabilities` |
| Watches | `integrations/source_watches.py` | `save`, `enqueue_due`, `record_result` |
| Cron | `integrations/watch_runner.py` | `run_once` |
| Sync | `integrations/goal_sync_service.py` | `GoalSyncService.sync_goal_sources`, `_supported_goal_step` |
| Normalize | `integrations/composio_normalizer.py` | `normalize_tool_result`, `_infer_events` |
| Forecast | agent workflow + `forecasting/reprice.py` / `BaselineForecastService` | `add_evidence` path |

`ManagedGatewayTransport` in `mcp_transport.py` still delegates to mock behavior. Live reads use `ComposioTransport` (`composio_transport.py`). Treat the transport layer as **two paths**, not one finished abstraction.

---

## Implementation inventory

### Generically implemented (common infrastructure)

- Composio toolkit catalog search and cache (`search_toolkits`, `_cached_toolkits`)
- Managed auth-config creation and OAuth link initiation for **any** toolkit slug
- Connected-account list / ACTIVE reconcile / status polling
- Tool listing + heuristic read-only classification (write-token reject)
- Recipe persistence, goal-scoped sync jobs, owner isolation
- Watch store, due enqueue, pause/stop/restart, Cron runner process
- Raw record fingerprint storage and owner-scoped dedupe
- Shared evidence workflow and forecast publish when `new_records` is non-empty
- Frontend plugin catalog shell and Evidence source workspace

### Partially implemented

- Resource discovery: preferred tools only for GitHub + Notion; others depend on lucky tool names
- Recipe construction: schema-driven argument fill, but semantic tool choice is hard-coded for GitHub/Notion
- Event normalization: rich for GitHub; Notion content hash only; generic status/duration stub otherwise
- “Proves goal progress”: mostly LLM evidence-agent judgment; deterministic withhold only for GitHub commit≠LeetCode-solved
- Notion monitoring UX: API supports `scope=resource`, UI always forces `parent`
- Autonomous Cron: poll + dedupe proven; new evidence / forecast / history **not** proven

### Provider-specific (required today)

- Preferred discovery tools: `GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER`, `NOTION_SEARCH_NOTION_PAGE`
- Notion pagination, title filtering, date-mention titles, URL synthesis, child BFS
- GitHub commit/PR/issue event inference and SHA fingerprints
- Notion markdown fingerprints (`page_id` + markdown)
- Goal-sync allowlists for Notion/GitHub tools (`_supported_goal_step`)
- Parent-watch API restriction: Notion only (`source_api.py`)
- NeetCode synonym + commit-only solution withhold policy

### Missing / not implemented for advertised providers

- Preferred resource tools for Gmail, Calendar, Drive, Sheets, Strava, Slack, Figma
- Provider-specific normalizers / evidence metrics for those toolkits
- Recipe allowlists / activity-type UX beyond GitHub/Notion
- Webhook ingestion (polling only)
- Notion database scopes (changelog marks outstanding)
- Typed error taxonomy: permission vs empty vs unsupported tool vs rate limit
- Automatic “this evidence proves the success metric” without LLM for non-GitHub cases

### Not verified (live)

- Fresh OAuth Pending→Connected for every advertised toolkit
- Cron → `records_new ≥ 1` → forecast change → new published history point
- New Notion child under a shared parent
- Any Gmail / Calendar / Drive / Sheets / Strava ingest affecting a goal
- Complete enumeration of all Notion-accessible pages (picker is bounded)

---

## Ten-capability scalability matrix

Question: does adding a **new Composio toolkit** automatically enable each step?

| # | Capability | Classification | Citation |
| --- | --- | --- | --- |
| 1 | Connect through OAuth | **GENERICALLY IMPLEMENTED** | `ComposioIntegrationGateway.initiate_connection` / `ensure_auth_config`; `IntegrationGatewayService.connect_managed` |
| 2 | Discover authorized resources | **PARTIALLY IMPLEMENTED** | `list_resources`: preferred map only `github`/`notion`; else first `list_*` name match; else `[]` |
| 3 | Understand available read operations | **GENERICALLY IMPLEMENTED** | `list_tools` + `MCPReadPolicy.classify_tool` → dynamic `*.read` capabilities |
| 4 | Select relevant resources for a goal | **PARTIALLY IMPLEMENTED** | Connected: `rank_resources` token overlap; disconnected: LLM source planner. No content understanding |
| 5 | Create a valid sync recipe | **PARTIALLY IMPLEMENTED** | `_select_capabilities` / `_arguments_for_resource`; Notion/GitHub required resources + tool prefs; others `return True` with weak selection |
| 6 | Fetch meaningful activity/progress | **PROVIDER-SPECIFIC** | Meaningful structure proven for GitHub commits/PRs/issues and Notion page bodies; no prefs for Gmail/Strava/etc. |
| 7 | Normalize into useful evidence | **PROVIDER-SPECIFIC** | `_infer_events` GitHub branch; Notion hash; else generic stub summary |
| 8 | Identify whether evidence proves progress | **PARTIALLY IMPLEMENTED** | Evidence-agent prompt + GitHub `withhold_commit_only_solution_claims`; no general deterministic validator |
| 9 | Monitor future changes automatically | **PARTIALLY IMPLEMENTED** | Watches + Cron generic; Notion parent expansion provider-specific; Cron new-delta **NOT VERIFIED** |
| 10 | Update forecasts from new evidence | **GENERICALLY IMPLEMENTED** *(once records exist)* | `GoalSyncService` → `add_evidence` workflow → publish; path is shared |

**Interpretation:** Steps 1, 3, and 10 are the generic platform. Steps 2 and 4–9 still require provider engineering or remain unproven. Dynamic tool discovery yields **executable tool names**, not **semantically correct evidence workflows**.

---

## Notion root-cause analysis

### Why Codex asked for a “Book Reports” parent

Production changelog (`IMPROVEMENT_CHANGELOG.md`, 2026-10-23): the authorized Notion picker returned about **ten** pages and **no “Book Reports” parent**. Unit/E2E fixtures use that name; that is **not** live account proof.

**A. Why the ~10 accessible pages (including “Oct 20th book report”) are insufficient for the new-child test**

New-child discovery expands **children of a watched parent** (`GoalSyncService` parent_ids + `list_notion_child_pages` / `notion_scope.discover_child_page_ids`). Watching the leaf “Oct 20th book report” discovers children **of that leaf**, not siblings under an unshared “Book Reports” container. Search only returns pages **shared with the integration**. Absence of the parent is an **OAuth/share boundary**, not a missing row in a workspace-wide listing.

**B. Can “Oct 20th book report” already be monitored for content updates?**

**Yes.** Recipe markdown tools + content fingerprint. Cron already called `NOTION_GET_PAGE_MARKDOWN` on approved watches with `records_new=0` (unchanged content). That is existing-page monitoring, not new-child discovery.

**C. Is a parent inherently necessary?**

| Workflow | Parent required? |
| --- | --- |
| Content updates of a known page | **No** (API `scope=resource`) |
| Discover newly created child pages | **Yes** |
| Product UI automatic monitoring | **Forced parent** for all Notion watches (`EvidenceSourceWorkspace.tsx` line 157) |

**D. Page picker vs manual IDs**

Accessible titled pages come from `NOTION_SEARCH_NOTION_PAGE`. Users select; IDs are stored in recipe arguments. No dedicated “paste page ID” UX. Untitled / opaque-UUID titles are dropped.

**E. Error distinction**

**Partial / poor.** Empty search → empty list + UI copy. Discovery exceptions in planner → logged, treated as `[]`. Missing content tool → `SemanticProviderError`. Sync failures collapse to generic “permission or provider error” / “Source sync failed…”. Not a typed 403 vs empty vs unsupported taxonomy.

**F. Pagination completeness**

**No.** Notion discovery follows at most `_RESOURCE_DISCOVERY_PAGE_LIMIT` cursor pages and caps results (`composio_gateway.py`). Stops if schema lacks `start_cursor`. Does not guarantee all accessible pages.

**G. Hierarchy literacy required?**

For new-child / “Watch area(s)” flows: **yes**. For content sync of a selected page: less so, but UI still labels Notion monitoring as parent/area.

**H. Low-friction onboarding within Notion’s model?**

**Partially possible:** Connect → share pages → pick titled pages → save → sync is proven for leaf content. Gaps: must share the correct parent for children; picker truncation; search ≠ hierarchy; watches need feature flag + Cron; databases unsupported.

**I. Notion-imposed vs PlayItOut-imposed**

| Notion-imposed | PlayItOut-imposed |
| --- | --- |
| Explicit share with integration | UI forces `scope=parent` for every Notion watch |
| Search only over shared pages | Hardcoded search + content-tool allowlists |
| No workspace-wide listing | Bounded pagination; drop untitled results |
| Child visibility requires shared parent | No database scope; Cron/env complexity; competing web scheduler historically |

**Do not conflate:** existing-page update monitoring ≠ new-child discovery ≠ parent/database monitoring ≠ OAuth share boundaries.

---

## Cron verification matrix

| # | Stage | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Cron Job configured | **VERIFIED LIVE** | User-provisioned `playitout-source-watch` `*/15`; not in `render.yaml` Blueprint |
| 2 | Cron Job invoked | **VERIFIED LIVE** | Scheduled/manual success after env repair (changelog 2026-10-23) |
| 3 | Cron read real provider data | **VERIFIED LIVE (Notion)** | 18:30 UTC: 2 markdown calls, 1 normalized record; later zero-due runs while web asleep |
| 4 | New evidence persisted | **NOT VERIFIED (Cron)** | Cron logs `records_new=0`; manual path **VERIFIED LIVE** |
| 5 | Forecast updated | **NOT VERIFIED (Cron)** | No agent workflow when zero new; manual 10.6%→15.1% **VERIFIED LIVE** |
| 6 | Published history changed | **NOT VERIFIED (Cron)** | Manual history yes; Cron had nothing new to publish |

**Do not mark automation working because the scheduler returned success.** A successful Cron with `records_new=0` proves poll + dedupe, not autonomous evidence.

**GitHub as Cron probe:** Code supports `scope=resource` watches without Notion parent. Manual GitHub sync is live-proven. **A Cron GitHub watch with `records_new≥1` was not documented.** That is the cleanest way to prove stages 4–6 without Notion parent share.

`watch_runner.run_once` itself has **no dedicated unit test** (IMPLEMENTED BUT NOT TESTED). Job claim / watch enqueue / parent expand are mock/Postgres tested.

---

## Scalability and abstraction gaps

### Where provider-specific adapters are fundamentally necessary

- Resource listing APIs differ (repos vs pages vs calendars vs mail threads)
- Incremental cursors / webhooks differ
- Payload shapes and identity keys differ (SHA vs page+markdown vs message id)
- Mapping activity → goal success metric is domain semantics, not transport

A healthy architecture accepts thin provider adapters for discovery, identity, and event extraction, while keeping OAuth, jobs, watches, dedupe, and publish generic. PlayItOut has the outer spine. It does **not** yet have a clean adapter interface that forces new providers to implement those thin contracts; instead, special cases are `if toolkit_slug == "notion"` / `if plugin_id == "github"` branches inside shared modules.

### True incremental cost of a new provider (honest estimate)

| Work item | Effort |
| --- | --- |
| OAuth via Composio slug | Low (already generic) |
| Preferred discovery tool + pagination rules | Medium |
| Recipe tool selection + argument schemas + UI activity types | Medium |
| Normalizer events + fingerprints | Medium–High |
| Goal-progress policy (false evidence risk) | High |
| Watch/incremental strategy | Medium–High |
| Mock + authenticated tests + one live acceptance | High |

**Adding a catalog logo is cheap. Adding a defensible evidence provider is a multi-day to multi-week adapter.**

### Dynamic discovery critique

`list_tools` + write-heuristic classification produces a **capability catalog**, not a workflow. Recipes for non-GitHub/Notion plugins can save `return True` steps that are executable and still semantically wrong (wrong tool, wrong arguments, empty resources, nonsense evidence). That is the core scalability failure mode.

---

## User-friction analysis

Ideal: Connect → auto-discover → approve once → background → evidence → forecast.

Actual common path today:

1. Open Plugins; connect toolkit (OAuth redirect; fresh Pending→Connected still fragile in reports)
2. Open a goal’s Evidence workspace (second surface)
3. Wait for resource discovery (Notion ~5s in production notes)
4. Manually select resources / activity types
5. Save recipe
6. Optionally enable Monitor (feature flag; Notion forced to “area/parent”)
7. Either click Sync or wait for Cron
8. Interpret “No new updates” vs actual forecast movement

### Friction inventory

| Friction | Avoidable? |
| --- | --- |
| Separate Plugins vs Evidence surfaces | Product design |
| Manual resource selection after connect | Partially unavoidable; ranking helps but does not auto-approve |
| Notion parent/area concept for leaf pages | PlayItOut design (UI force) |
| Must share Notion pages with integration | Notion-imposed |
| Must create/share special parent for new-child test | Notion share + PlayItOut parent model |
| Feature flag + external Cron for autonomy | Incomplete productization (`render.yaml` has no Cron) |
| Opaque tool/capability language in recipes | Incomplete UX |
| Manual Sync still primary verified path | Incomplete autonomous verification |
| Collapsed provider errors | Incomplete implementation |
| Advertised Gmail/Calendar/Strava with no proven ingest | Product overclaim risk |

---

## Risks and limitations (by product impact)

| Rank | Risk | Impact |
| --- | --- | --- |
| P0 | False evidence / overclaiming progress (esp. GitHub commits as “solved”; LLM interpretation of Notion text) | Incorrect forecasts; trust failure |
| P0 | Catalog implies Gmail/Calendar/Strava/etc. work like GitHub/Notion | User connects and finds empty discovery or useless sync |
| P0 | Cron success mistaken for end-to-end autonomy | False operational confidence |
| P1 | Duplicate / missed Notion children due to share + parent model | Missed evidence or surprise empty watches |
| P1 | Bounded Notion pagination hides shared pages | User believes resource does not exist |
| P1 | Tenant isolation regressions in job claim / raw IDs | Cross-user data risk (currently tested; keep gated) |
| P2 | Blueprint drift (`render.yaml` lacks Cron) | Non-reproducible ops |
| P2 | LLM cost on evidence path when new records appear | Budget risk |
| P2 | Connector version drift (Composio tool renames) | Silent recipe breakage |

---

## Recommended improvements

### P0

1. **Prove Cron stages 4–6 on GitHub resource watches** (no Notion parent dependency). Acceptance: due watch → Cron `records_new≥1` → forecast receipt → new history point; optionally while web asleep.
2. **Stop advertising unsupported toolkits as equivalent.** Gate catalog to “Connectable” vs “Evidence-ready (GitHub/Notion)” until adapters exist.
3. **Separate Notion UI scopes:** content watch (`resource`) vs area/child discovery (`parent`). Do not force parent on leaf pages.
4. **Typed provider errors** for empty / unsupported tool / permission / rate limit.

### P1

5. **Provider adapter contract:** `discover_resources`, `preferred_read_tools`, `normalize_events`, `identity_fingerprint`, `incremental_cursor` — require these for “Evidence-ready.”
6. **Notion database scope or explicit “not supported” UX.**
7. **Complete live re-run of Notion picker pagination** after #16; document actual page counts.
8. **Unit-test `watch_runner.run_once`** with fake stores.

### P2

9. Put Cron in `render.yaml` or documented IaC.
10. Webhooks where providers support them (GitHub first).
11. Deterministic goal-metric extractors for high-value domains before LLM.

### Minimal path to a seamless experience (no rewrite)

1. Treat **GitHub + Notion leaf content** as the only Evidence-ready providers in UX.  
2. Fix Notion watch scope UX (resource vs parent).  
3. Prove **one** Cron new-evidence → forecast path on GitHub.  
4. Keep Composio OAuth for other toolkits but label them Connect-only until an adapter ships.  
5. Add the thin adapter interface before the next “third provider.”

That path yields a honest two-provider product with real autonomy proof, without pretending the catalog is a platform.

---

## Product traces (conceptual; do not invent success)

### “Read 24 books this year” + Notion

| Step | Status |
| --- | --- |
| Create goal | Works (agent/manual) |
| Connect Notion | Works (Composio) |
| Discover relevant tracker | **Partial** — picker of shared titled pages; Book Reports parent missing in live account |
| Approve once | Works (recipe save) |
| Background detect new entry | **Not verified** for new child; content change of watched page would dedupe until markdown changes |
| Legitimate evidence | **Partial** — LLM interprets markdown; not a structured “books finished” metric |
| Forecast update | Works **if** new records pass evidence path (manual proven; Cron new-delta not) |

### GitHub coding progress

Manual repo+commits → normalize → dedupe → evidence → forecast: **VERIFIED LIVE**. Commit≠solved policy: **TESTED**. Cron watch path: **NOT LIVE-VERIFIED**.

### Gmail hiring / Calendar interviews / Strava fitness

Connect may work. Discovery/normalize/goal proof: **NOT IMPLEMENTED** at Evidence-ready depth. **No live ingest claims found.**

---

## Sources of evidence (this audit)

- Code on `f12a153` as cited above
- Tests: `test_mcp_integration.py`, `test_source_watches.py`, `test_source_planner.py`, `test_notion_scope.py`, `test_goal_sync_jobs*.py`, `test_github_solution_policy.py`
- `docs/IMPROVEMENT_CHANGELOG.md` Cron/Notion/GitHub entries 2026-10-21 through 2026-10-23
- Companion matrices: `PLUGIN_CAPABILITY_MATRIX.md`, `AUTONOMOUS_EVIDENCE_PIPELINE_AUDIT.md`

**Not used as proof of production:** unmerged draft PR implementations (#18–#20), mocked Playwright alone, catalog logos, Composio tool presence without PlayItOut adapter depth.
