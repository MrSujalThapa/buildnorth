# Composio scalability implementation

Engineering pass on `feat/composio-scalable-connectors`. This is not a second integration system and not a new audit. Composio still owns OAuth and tool execution. Recipes, watches, sync jobs, raw records, and the evidence workflow are unchanged stores.

## 1. What changed

Provider-specific read semantics now live in `integrations/provider_contract.py`. The shared gateway, normalizer, goal sync, and source planner call that contract instead of guessing a tool.

- Resource discovery uses an adapter's declared discovery tool, or a schema-checked choice. If neither exists, discovery raises `unsupported_capability`. It no longer saves the first `list_*` tool.
- Sync arguments are filtered to the live tool schema. Unknown keys, including a guessed `since`, are dropped. Missing required keys raise `invalid_tool_arguments`.
- Failed provider payloads become `IntegrationProviderError` with a safe message, a `kind`, and `retryable`. The HTTP handler returns that kind. Retryable failures do not mark the connection `error`.
- Goal recipes fail closed unless the adapter names the tool as a supported read.
- Plugin catalog JSON includes `evidence_readiness` and `readiness_detail`. The resources endpoint is still a list.

## 2. Adapter contract

`ProviderAdapter` is a small base class, not a new framework. A provider implements only the operations PlayItOut already performs:

- identity and readiness
- resource discovery tool
- which read tools may be saved for a goal
- pagination arguments that exist on the schema
- fingerprint and observations
- parent-watch support
- whether content monitoring requires a parent

`prepare_call_arguments` and `classify_provider_failure` are shared. OAuth, recipe rows, watches, and forecast publication stay where they were.

## 3. Providers migrated

**GitHub** (`evidence_capable`). Repository discovery, commit / pull request / issue reads, SHA fingerprints, owner-scoped recipes, and incremental `since` only when the schema declares it. A commit remains `repository_activity` with `promotes_to_verified_outcome: false`. The existing commit-is-not-a-solved-problem withhold stays.

**Notion** (`evidence_capable`). Search discovery, schema-validated pagination, title filtering that drops empty and UUID titles, markdown fingerprints, and content reads. `content_monitoring_requires_parent` is false. `watch_scopes` is `resource` and `parent`. Parent expansion runs only for an active parent watch. A page edit is `raw_content`, not a completed book.

## 4. How to add a provider

1. Add a `ProviderAdapter` subclass and register it in `_ADAPTERS` under the plugin id.
2. Set `discovery_tool` or `choose_discovery_tool` from real Composio tool names.
3. Implement `select_tool_names` so a recipe is saved only when a meaningful read exists.
4. Implement `fingerprint` and `observations`. Leave `metric` empty when the payload is not a supported measurement.
5. Keep `readiness` at `connectable` until an authorized account has been acceptance-tested. Do not set `autonomous_verified` from a unit test.
6. Add fixture tests for schema changes, missing arguments, duplicates, updates, and the evidence classification.

Until that adapter exists, `ConnectableAdapter` refuses discovery and goal reads.

## 5. What stays provider-specific

Tool slugs, required argument names, pagination keys, identity fields (GitHub SHA, Notion markdown hash, calendar id + revision), and which observations are activity versus raw content. Notion is still the only adapter with `supports_parent_watch`. Composio account selection, the read-only tool policy, and the evidence workflow are shared.

## 6. Capability levels

| Level | Meaning | Set for |
| --- | --- | --- |
| `connectable` | OAuth can connect the app. PlayItOut will not invent a goal-evidence recipe. | Gmail, Calendar, Drive, Strava, Slack, Sheets, Figma, and any unknown toolkit. Manual and CSV are in-app, not Composio. |
| `evidence_capable` | The adapter can discover approved resources, run a validated read, normalize observations, and hand them to the existing workflow. | GitHub and Notion. Manual sync of those two was already shown live. |
| `autonomous_verified` | A scheduled run detected new provider data and published evidence, a forecast update, and history. | Not set. A unit test or HTTP 200 is not this level. |

`GET /api/v1/plugins` includes the two fields on each plugin definition. The web `PluginView` type accepts them. The plugins page was not redesigned.

## 7. Safety and normalization

An observation carries provider, source event id, observed time, ingestion time, activity type, optional metric, classification, `validation_status: unverified`, and `provenance.promotes_to_verified_outcome: false`.

- Raw content, observed activity, and verified outcomes stay distinct. This pass does not upgrade activity into a verified achievement.
- Unknown schemas can still be stored as raw rows. They do not receive a fabricated numeric progress metric.
- Empty successful reads stay an empty record list. Authentication, permission, not-shared, not-found, rate limit, timeout, schema mismatch, and upstream failures are separate kinds. Messages do not include the raw provider payload.
- Write tools stay rejected by the existing read-only policy, including when a description says the write is harmless.
- The source planner records `discovery_issues` and does not call paid inference when discovery fails.

## 8. Tests executed

Commands were run in the `buildnorth-composio` worktree. Python is 3.12. The database was a throwaway Postgres 17 container on `127.0.0.1:54329`. The local Supabase database on port 54322 was not migrated.

- `uv run python scripts/check_ruff_baseline.py` — no new findings. 562 existing findings remain.
- `uv run python scripts/check_mypy_baseline.py` — no new errors. 368 existing errors remain.
- `uv run python scripts/check_architecture.py` — passed.
- `uv run python scripts/check_migrations.py` — passed (22 required tables, 22 files).
- `uv run python scripts/db_migrate.py` against `127.0.0.1:54329/postgres` — applied migrations 0001 through 0022.
- `uv run python -m pytest -q --tb=line` with `PM_DATABASE_URL` and `PM_TEST_DATABASE_URL` pointed at that database — 670 passed, 3 skipped, 1 failed.
- The failure is `apps/api/tests/test_phase2_inference.py::test_semantic_retries_share_one_wall_time_deadline` (`assert provider.calls == 2`, actual 1). A second run of that test failed the same way. `agents/completion.py` is unchanged. The test sleeps 0.04 seconds inside a 0.06 second `asyncio.timeout`, and the Windows timer cancelled the first sleep before a second attempt. It does not call the provider adapters.
- `npm run typecheck --workspace @personal-markets/web` — passed.
- `npm run test --workspace @personal-markets/web` — 32 files, 108 tests passed.
- `npm run build --workspace @personal-markets/web` — passed.
- No paid inference. No production credentials or Composio permission changes. No live Google Calendar read. `evaluate_openai_baseline.py` was not run, so it could not write a baseline artifact or spend a key.

## 9. Third provider

Google Calendar has a read-only adapter covered by mocked schemas: list-calendars discovery, event-list selection, `calendarId` required, `updatedMin` and `pageToken` only when present, fingerprints of event id plus revision, and `scheduled_event` observations with no metric.

Readiness stays **`connectable`**. Fixture tests are not authenticated acceptance. A scheduled event is not proof it occurred. The provider is not `evidence_capable` and not `autonomous_verified`.

## 10. Remaining limitations

- Nothing in this pass is `autonomous_verified`. Scheduled new-data to forecast to published history is still unverified. Cron was not changed.
- Calendar, Gmail, Drive, Strava, Slack, Sheets, and Figma are connectable only.
- Notion resource-level watches work in the API and goal sync. The evidence-source UI still forces Notion watches to parent scope. That component was not edited.
- Plugin presentation copy elsewhere can still describe reads the adapter will refuse. The catalog descriptions for the connectable apps were corrected. A broader plugins-page redesign was left for the UI pass.
- Opening resources for a connectable provider now returns `unsupported_capability` instead of an empty success list.

## 11. Files that may conflict with the other in-progress pass

The primary checkout was left on `feat/playitout-next-pass` at `92c774d`. This branch was cut from `origin/main` (`f12a153`). Likely overlap if that work also edits integrations or plugin types:

- `apps/api/src/personal_markets/integrations/composio_gateway.py`
- `apps/api/src/personal_markets/integrations/composio_normalizer.py`
- `apps/api/src/personal_markets/integrations/composio_transport.py`
- `apps/api/src/personal_markets/integrations/mcp_service.py`
- `apps/api/src/personal_markets/integrations/goal_sync_service.py`
- `apps/api/src/personal_markets/integrations/plugins.py`
- `apps/api/src/personal_markets/agents/source_planner_service.py`
- `apps/api/src/personal_markets/ports.py`
- `apps/api/src/personal_markets/main.py`
- `apps/api/src/personal_markets/core/errors.py`
- `apps/web/src/api/client.ts` (optional readiness fields only)

Not edited, and still the UI dependency: `apps/web/src/features/goals/EvidenceSourceWorkspace.tsx` forces Notion `scope: "parent"`. What If, Goal Architect, radar/profile, markets, collections, Cron, and marketplace code were not part of this branch.
