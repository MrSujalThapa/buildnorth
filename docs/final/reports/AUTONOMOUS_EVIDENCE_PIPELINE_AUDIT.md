# Autonomous Evidence Pipeline Audit

**Audit date:** 2026-10-23  
**Code:** `origin/main` @ `f12a153`  
**Constraint:** Scheduler HTTP/process success ≠ end-to-end autonomy.

---

## Pipeline under audit

```text
Connected provider
  → approved goal sync recipe
  → source watch (optional)
  → scheduled trigger (Render Cron → watch_runner.run_once)
  → resource fetch (Composio tool)
  → deduplication (payload_hash / SHA / Notion page+markdown)
  → normalized RawSourceRecord
  → (if new) goal evidence workflow
  → numerical forecast recompute
  → published history snapshot
```

Entry point: `python -m personal_markets.integrations.watch_runner`  
Implementation: `integrations/watch_runner.py::run_once`  
Job execution: `integrations/goal_sync_worker.py::execute_goal_sync_job`  
Sync: `integrations/goal_sync_service.py::GoalSyncService.sync_goal_sources`

Production Cron is **dashboard-provisioned** (`playitout-source-watch`). It is **not** declared in `render.yaml`. Config drift is a real ops risk.

After PR #14 (`638bc41`), the awake web worker **no longer** `enqueue_due` for watches and **cannot** claim `origin=watch` jobs. Manual Sync remains on the web worker. Autonomy depends on Cron.

---

## Stage-by-stage verification

| Stage | Implemented | Unit / contract | Integration | Real provider | Prod scheduled | Failure / retry / idempotency / tenant |
| --- | --- | --- | --- | --- | --- | --- |
| Connect | Yes | MCP reconcile tests | Playwright launch | Notion+GitHub live | N/A | Fresh OAuth all toolkits incomplete |
| Discover | Yes | Picker/pagination tests | — | Notion ~10 pages; GitHub repos | N/A | Book Reports parent **BLOCKED BY EXTERNAL PERMISSION** |
| Approve recipe | Yes | Planner/recipe tests | Live save | Notion+GitHub | N/A | Owner-scoped |
| Create watch | Yes | `test_source_watches.py` | Mocked Playwright | Live “Monitoring 2 of 2” Notion | N/A | Owner+goal; Notion UI `scope=parent` |
| Scheduled trigger | Yes | **No `watch_runner` test** | Postgres claim tests | Cron process live | **VERIFIED LIVE** | Env malformation caused early fails; stranded → `timed_out`, no auto billable retry |
| Fetch | Yes | Mocked sync | — | Cron Notion markdown **VERIFIED LIVE**; GitHub Cron **NOT VERIFIED** | Notion yes | Active-watch allowlist recheck |
| Dedupe | Yes | MCP normalize/dedupe tests | Live double-sync | Manual + Cron `records_new=0` | Yes (unchanged) | Owner-scoped raw IDs |
| Normalize | Yes | Same | Live document body | Notion+GitHub | Cron read yes | Provider status ≠ commitment |
| Goal match / evidence agent | Yes if new | Workflow tests | Manual live | Manual **VERIFIED LIVE** | Cron **NOT VERIFIED** | Fail-closed unsupported activities |
| Forecast recompute | Yes if new | Reprice tests | Manual live | Manual 10.6%→15.1% | Cron **NOT VERIFIED** | Unchanged skips publish |
| Published history | Yes if new | History tests | Manual live | Manual yes | Cron **NOT VERIFIED** | Immutable snapshots |

---

## Six-proof Cron matrix

| # | Claim | Result | Detail |
| --- | --- | --- | --- |
| 1 | Cron configured | **VERIFIED LIVE** | `*/15`, Docker `uv run --no-sync python -m personal_markets.integrations.watch_runner`, env group with `COMPOSIO_API_KEY`, `PM_DATABASE_URL` (changelog 2026-10-23) |
| 2 | Cron invoked | **VERIFIED LIVE** | Multiple scheduled successes after env repair; empty-due and processing runs |
| 3 | Cron read real provider data | **VERIFIED LIVE (Notion)** | 18:30 UTC: two watches → one job → two `NOTION_GET_PAGE_MARKDOWN` calls → one normalized record; later runs while web asleep with no due watches |
| 4 | New evidence persisted | **NOT VERIFIED** | Cron: `records_new=0`. Manual path proven earlier |
| 5 | Forecast updated | **NOT VERIFIED** | No workflow when zero new records |
| 6 | Published history changed | **NOT VERIFIED** | Nothing new to publish |

**Verdict:** Cron is a **working scheduled poller with live Notion read + dedupe**. It is **not** a verified autonomous evidence→forecast system.

---

## Manual path (contrast)

Documented live (changelog 2026-10-21 era, still the strongest E2E claim on main):

- Authorized Notion page + GitHub commits synced
- Fingerprint repair (`b395e37`): Notion page+markdown, GitHub SHA
- Forecast movement **10.6% → 15.1%** on reading goal after first relevant ingest
- Immediate repeat: `records_new=0`, forecast unchanged

That proves Connect→approve→**manual** sync→evidence→forecast→history for Notion+GitHub. It does **not** transfer to Cron without a new-delta observation.

---

## GitHub Cron probe (recommended, not executed)

Code already supports:

- `scope=resource` watches for non-Notion plugins (`EvidenceSourceWorkspace.tsx`)
- No parent expansion for GitHub (`GoalSyncService` parent_ids Notion-only)
- Live manual GitHub fetch/normalize/dedupe/forecast

**Missing production evidence:** an active GitHub watch whose due Cron run lists commits with `records_new≥1` and a new history point.

This probe would verify stages 4–6 **without** Notion’s missing parent and should be preferred for acceptance.

---

## Notion-specific autonomy blockers

1. **New-child workflow** requires a shared parent; live picker lacked “Book Reports.”  
2. UI forces Notion watches to `parent`, conflating leaf content monitoring with area discovery.  
3. Content changes on an already-watched page **would** create new fingerprints when markdown changes; Cron never observed such a change in logged runs.  
4. Database scopes are outstanding.

---

## Failure, retry, isolation

| Concern | Behavior | Evidence |
| --- | --- | --- |
| Retry | Stranded jobs → `timed_out`; no automatic billable workflow replay | `test_stranded_sync_is_reported_without_automatic_retry` |
| Idempotency | Single active job; fingerprints; watch checkpoint after enqueue | Job/watch tests + live zero-new |
| Tenant isolation | Owner-scoped watches/jobs/raw | Postgres + in-memory tests |
| Bound | `max_jobs` 1–5 (default 1) | `watch_runner.run_once` |
| Consent | Active watch URI allowlist before read; parent revoke recheck | `test_parent_watch_reads_only_discovered_children_and_rechecks_revocation` |

---

## Feature flags and productization gaps

| Gate | Effect |
| --- | --- |
| `VITE_BACKGROUND_MONITORING` | Hides Monitor UI until true (enabled in prod after Cron existed) |
| Dashboard-only Cron | Not reproducible from repo Blueprint |
| Separate Plugins vs Evidence UX | Extra steps vs ideal one-surface flow |
| Silent Cron | UI shows next check / last error; users may not see autonomous work |

---

## Contradiction log (reports vs reality)

1. Early upgrade notes said Cron untouched / card-blocked — **superseded** by 2026-10-23 live Cron sections. Use dated later entries.  
2. “Resource watches” in prose vs Notion UI always `scope=parent` — naming mismatch.  
3. Outcome matrices marking sync/dedupe **PASS** include manual + Cron zero-new; they do **not** mean autonomous new-evidence PASS.  
4. Empty Cron exit 0 was correctly later called **failed autonomous acceptance**, then fixed for due processing — still not stages 4–6.  
5. Parent-watch unit tests PASS ≠ live child discovery.  
6. Draft PRs #18–#20 are **not** on `f12a153` production path for plugins (MCP personal agents / ML / hiring). Do not credit them as live plugin autonomy.

---

## Scoring note for “percent seamless”

If forced to score the **ideal Connect→forecast autonomous loop** as ten equal stages (see forensic audit § Ten-capability matrix), using only **VERIFIED LIVE** or fully **GENERICALLY IMPLEMENTED and exercised** credit:

| Stage | Credit |
| --- | --- |
| 1 OAuth | 1.0 (GitHub/Notion) |
| 2 Discover | 0.6 (two providers, bounded) |
| 3 Read ops | 0.8 (generic list; weak semantics) |
| 4 Select for goal | 0.4 |
| 5 Recipe | 0.5 |
| 6 Fetch meaning | 0.4 (two providers) |
| 7 Normalize | 0.4 |
| 8 Proves progress | 0.3 |
| 9 Auto monitor | 0.35 (poll+dedupe; no new-delta) |
| 10 Forecast from new | 0.5 (manual yes; Cron no) |
| **Sum** | **5.25 / 10 = 53%** |

This is an **audit scoring method**, not a product KPI. It deliberately under-credits catalog-only providers. If averaged across **all advertised** Composio apps, the percentage would be substantially lower.

---

## What would constitute a true autonomous PASS

1. Active watch (GitHub resource **or** Notion page with content change **or** shared parent with new child).  
2. Cron: `scheduled>0`, `processed>0`, provider call, **`records_new≥1`**.  
3. Evidence workflow run with receipt.  
4. Forecast probability change **or** explicit unchanged with reason.  
5. New published history point when material.  
6. Optional: same while web service is asleep **and** watch is due.

Until then, the accurate public claim is:

> Scheduled authorized polling and deduplication work for approved Notion pages. Autonomous detection of new evidence and forecast updates via Cron has not been demonstrated.
