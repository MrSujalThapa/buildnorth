# Social and Profile product audit

Scope: PR #33 at `79a7645`, reviewed in isolated branch `audit/social-profile-product`. PR #35 (`fcf09be`) and PR #36 (`cdfd1f6`) were inspected read-only. No deployment, production writes, or feature-branch merge occurred.

## Evidence level

The rendered screenshots below come from Playwright in Chrome at desktop and 390 px mobile widths, using representative mocked API responses. Backend social operations were exercised with two isolated test principals through FastAPI's HTTP boundary and in-memory repositories. These checks do **not** establish actual Clerk, production PostgreSQL, live social data, or deployed-branch acceptance. PR #33 is unmerged, so production cannot show these screens yet. No paid inference was invoked.

Screenshots: [Discover desktop](assets/discover-desktop.png), [Discover mobile](assets/discover-mobile.png), [public market desktop](assets/public-market-desktop.png), [public profile mobile](assets/public-profile-mobile.png), [own profile desktop](assets/own-profile-desktop.png), [own profile mobile](assets/own-profile-mobile.png).

## Five most serious findings and fixes

| Severity / category | Actual behavior | Intended behavior | Evidence / source | Change / remaining proof |
| --- | --- | --- | --- | --- |
| Critical / privacy | Public profile activity counted private-goal events. An outsider could infer dates and volume of private work, including when no private goal details were exposed. | Public heatmap only counts activity for currently public active goals; owner can see own full activity. | `social/service.py`, `social/postgres.py`, `social/adapters.py`; new two-principal regression test. | Fixed in both repositories, including after unpublish. Production PostgreSQL cross-user test remains needed. |
| High / privacy | `fork_goal` copied the entire source success definition when no allowlisted field survived; it also copied the creator's personal resource constraints. | Fork only reviewed public contract fields into a new private goal. | `social/blueprint.py`; new fork privacy test. | Fixed. A blueprint without public success criteria now returns a domain conflict rather than copying private data. |
| High / functional | Discover, public profile subviews, and own Profile subviews rendered empty states while API requests failed or were still loading. | Errors and pending requests remain distinguishable from genuine emptiness, with retry. | `SocialPage.tsx`, `PublicProfileRoute.tsx`, `ProfileRoute.tsx`; browser retry test and screenshots. | Fixed for market, stars, follow graph and activity requests. Real network failures need deployed verification. |
| Medium / functional | After star/follow mutations, related cached lists and graph views could retain old counts and state. Failure was silent. | Invalidate affected queries and show action failure. | `PublicMarketRoute.tsx`, `PublicProfileRoute.tsx`. | Added relevant invalidation and alerts. Real refresh persistence and two-session synchronization remain unverified. |
| Medium / visual | Public profiles ignored an existing public photo URL and used a settings-like bordered card; mobile counts broke into separate lines. Discover creator buttons looked browser-native. | Personal, compact identity with photo and stable mobile hierarchy. | Before/after rendered public-profile screenshot; `social.css`, `PublicProfileRoute.tsx`, `SocialPage.tsx`. | Uses public photo when `has_photo`, flattens public identity layout, improves touch/focus targets. Real owner-upload-to-public-photo check remains. |

Additional correctness fix: public history now accepts only `published_forecast` rows, excluding synthetic and hypothetical source kinds. Public market opens at All history to avoid a nearly empty default month when authentic history is sparse. The two-point spike was closed in the subsequent remediation below; sparse history now shows dated observations without a line.

## Consumer journey review

- **Search/sort:** query and sort reach the public-market API. Only the first page is rendered; no pagination or result count. Fixture browser navigation passes; real database sorting/search performance not measured.
- **Follow/star:** authenticated backend endpoints and idempotent repeat actions pass isolated HTTP tests. The UI now reports failures and refetches relevant counters. A live two-Clerk-user journey has not run.
- **Publish/unpublish:** owner-scoped API test passes and hidden market disappears after unpublish. The public heatmap now hides its events too. Production propagation/cache behavior remains unverified.
- **Fork:** isolated API test shows a private goal owned by the visitor, idempotent retry, and no copied odds/evidence. Sanitized contract and personal-resource checks added. Real database transaction and creation UX still need deployment proof.
- **Profiles:** own editing, photo crop/upload mock, measured-parameter selection and refresh persistence pass browser fixture tests. The public profile shows activity and public markets; private radar is absent. Actual photo persistence and public delivery with signed-in users remain unverified.
- **Heatmap:** counts represent recorded social events, not all productivity across integrations. The public/private filtering is fixed, but its title should eventually explain the event scope. Narrow view scrolls horizontally; month labels remain dense.
- **Charts:** real API history is passed through, with no invented points. The follow-up remediation displays one or two dated published observations without a line; three or more retain the interactive chart.
- **Empty/error states:** the fixed views distinguish errors and emptiness. Fork and top-level profile errors have basic text but limited detail. Accessible dialog focus trapping and Escape handling still need dedicated verification.

## Five next product improvements

1. Complete a two-Clerk-user deployment journey: publish, inspect, follow, star, fork, refresh, unpublish, and verify private data stays inaccessible.
2. Resolve the sparse public-chart presentation without creating synthetic history; show discrete observations when only one or two publications are in range.
3. Make the public blueprint a practical starter: clarify measurable success criteria and milestones in plain language while keeping private evidence, resources and recommendations hidden.
4. Add pagination and visible result states to Discover and profile repositories; the current fixed API limits silently truncate larger catalogs.
5. Make the activity heatmap explain its recorded-event scope and improve month-label legibility on mobile.

## Pass 9 integration map

PR #36 defines an invited-owner API at `/api/v1/goals/{goal_id}/strategy-recommendations`: GET returns `LearningContext`, POST generates a grounded `RecommendationTrial`, `/{id}/feedback` records accepted/declined/ignored, and `/{id}/outcomes` records attempted state, measured value, confidence, timestamp and existing evidence IDs. It rejects unverified external relationship/research facts. It is **not merged into PR #33**, so no consumer recommendation UI was wired or populated here.

After branches merge, the natural private location is the owner Goal detail page: a small recommendation inbox next to progress and evidence, with one explicit Generate action; Accept/Decline; later Record attempt and Link evidence; and a history/details view explaining observed outcome and uncertainty. The agent must receive structured prior trials from PR #36's learning context. Avoid claiming that a recommendation caused later progress. Never expose trials, feedback, evidence IDs or agent context on public profiles or public blueprint responses. Public blueprints are inspiration and templates, not another user's private learning history.

PR #35 improves external-agent receipt and source-watch contracts. Future consumer evidence links should point to validated owner-scoped evidence/receipts; no public evidence link should be created by copying an external-agent payload. No #35 code was modified here.

## Prioritized integration checklist

1. Merge/rebase independently verified branches in an agreed order; resolve contract conflicts without copying private strategy data into public adapters.
2. Add private Goal-detail recommendation interface against PR #36's published types, using authenticated owner requests and honest pending/empty/failure states.
3. Run isolated PostgreSQL tests for two users against the combined branches, including private activity and fork isolation.
4. Run real Clerk browser tests at desktop/mobile and confirm persisted follow/star/fork/photo/parameter state after refresh.
5. Visually repair sparse charts and profile month labels, then review keyboard/dialog accessibility.
6. Only then deploy and verify the public/private boundary in production without writing to existing user markets during audit.

## Verification and limits

Focused backend social/profile tests: 11 passed before the final public-history assertion; the expanded social file passes 6/6. Frontend unit suite: 128/128 passed. Playwright Social: 4/4 desktop/mobile; Profile: 2/2 desktop/mobile. Frontend typecheck/build and architecture/migration checks passed. Tests use mocked UI responses and isolated two-user API principals; no live Clerk journey. Full backend suite passed locally (with expected skips); remote CI status is recorded on the draft PR. No migration changed.

## Follow-up remediation: sparse charts, pagination, blueprint, heatmap

- **Sparse published history:** One or two source-backed publications are displayed as separate percentage/date observations on public market pages and catalog tiles, without interpolation or artificial points. Three or more retain `OddsExplorer`. Playwright pixel snapshots cover one and two observations at desktop and 390 px mobile widths, plus an interaction assertion for three observations. Dates display in UTC to match publication timestamps. [Desktop](assets/public-sparse-desktop.png) · [Mobile](assets/public-sparse-mobile.png).
- **Discover:** `/api/v1/public/markets` now includes `total`, `limit`, and `offset` alongside the existing `items`. The PostgreSQL and in-memory repositories count the same public search scope, and ties have stable ID ordering. The React query key includes search and sort, fetches real offset pages, deduplicates cards by goal ID, shows loaded/total counts, and gives failed next pages an explicit retry. The browser fixture covers 25 results, a duplicate returned on page two, a failed page, recovery, search, and sort. [Desktop](assets/discover-paginated-desktop.png) · [Mobile](assets/discover-paginated-mobile.png). Offset pagination can still shift under simultaneous publishing; cursor pagination would be needed for a fully stable changing feed.
- **Blueprint:** Public detail and fork use the stored reviewed publication snapshot instead of rebuilding from a creator's subsequently edited private goal. The owner/visitor HTTP test mutates the source contract after publishing and verifies public detail and the new private fork keep the reviewed criteria, while the creator cannot access the visitor's fork. The frontend renders named success criteria, milestones, and explicitly published approach in plain language. No creator resources, evidence, strategy trials, or recommendations are copied. A legacy public goal with no stored criteria cannot be forked until republished.
- **Activity:** The heatmap now identifies the recorded event scope; public profiles explicitly say only events on public markets appear. Mobile labels show alternating months aligned to the same week grid, reducing collisions without changing event data. The prior public/private filtering remains. [Mobile public profile](assets/public-profile-mobile.png).

Verification: focused Social backend tests 8/8; full local backend suite passed with expected skips; frontend unit suite 128/128; Social/Profile Playwright 12/12 across desktop and mobile; Ruff, mypy, typecheck, lint, build, architecture and migration checks passed. All browser data above is mocked. Actual Clerk users, hosted PostgreSQL persistence and production deployment remain unverified; no production writes or paid inference were made.


## Follow-up remediation: sparse charts, pagination, blueprint, heatmap

This section supersedes the earlier sparse-chart gap in this audit.

- **Sparse published history:** One or two source-backed publications are displayed as separate percentage/date observations on public market pages and catalog tiles, without interpolation or artificial points. Three or more retain `OddsExplorer`. Playwright pixel snapshots cover one and two observations at desktop and 390 px mobile widths, plus an interaction assertion for three observations. Dates display in UTC to match publication timestamps. [Desktop](assets/public-sparse-desktop.png) and [mobile](assets/public-sparse-mobile.png).
- **Discover:** `/api/v1/public/markets` now includes `total`, `limit`, and `offset` alongside the existing `items`. The PostgreSQL and in-memory repositories count the same public search scope, and ties have stable ID ordering. The React query key includes search and sort, fetches real offset pages, deduplicates cards by goal ID, shows loaded/total counts, and gives failed next pages an explicit retry. The browser fixture covers 25 results, a duplicate returned on page two, a failed page, recovery, search, and sort. [Desktop](assets/discover-paginated-desktop.png) and [mobile](assets/discover-paginated-mobile.png). Offset pagination can still shift under simultaneous publishing; cursor pagination would be needed for a fully stable changing feed.
- **Blueprint:** Public detail and fork use the stored reviewed publication snapshot instead of rebuilding from a creator's subsequently edited private goal. The owner/visitor HTTP test mutates the source contract after publishing and verifies public detail and the new private fork keep the reviewed criteria, while the creator cannot access the visitor's fork. The frontend renders named success criteria, milestones, and explicitly published approach in plain language. No creator resources, evidence, strategy trials, or recommendations are copied. A legacy public goal with no stored criteria cannot be forked until republished.
- **Activity:** The heatmap now identifies the recorded event scope; public profiles explicitly say only events on public markets appear. Mobile labels show alternating months aligned to the same week grid, reducing collisions without changing event data. The prior public/private filtering remains. [Mobile public profile](assets/public-profile-mobile.png).

Verification: focused Social backend tests 8/8; full local backend suite passed with expected skips; frontend unit suite 128/128; Social/Profile Playwright 12/12 across desktop and mobile; Ruff, mypy, typecheck, lint, build, architecture and migration checks passed. All browser data above is mocked. Actual Clerk users, hosted PostgreSQL persistence and production deployment remain unverified; no production writes or paid inference were made.

## Real-user acceptance attempt (2026-10-25)

**Status: BLOCKED for the exit criterion.** This worktree has no configured Clerk test credentials, two authenticated test sessions, or local frontend Clerk configuration. PR #37 is an unmerged draft based on `feat/pass8-social-marketplace`; the deployed production site cannot validate this branch. No successful authentication was simulated or represented as real. No production data was changed.

A disposable PostgreSQL 17 database was started on local loopback port 55441 and migrated through `0023_social_marketplace.sql`. The new integration test `apps/api/tests/test_social_postgres_acceptance.py` uses actual `PostgresGoalRepository` and `PostgresSocialRepository` calls with two test identity IDs. It verifies publish, API service pagination/search, public detail and profile activity, follow, star, private fork, reconstructed repository persistence, fork owner isolation, reviewed blueprint stability after a private source edit, and public detail/activity/star-list revocation after unpublish. These are test identities, not Clerk accounts, and the test does not exercise HTTP authentication. The prior two-principal FastAPI tests use `auth_bypass_principal` and in-memory repositories.

Actual PostgreSQL integration results: 6/6 passed including the new Social lifecycle and existing upload persistence tests. Focused Social/Profile API tests: 14/14 passed. Frontend unit tests: 128/128 passed. Typecheck and build passed. Ruff passed for the new test. The repository mypy baseline check was run separately; the direct single-file mypy invocation could not resolve this monorepo package and is not treated as a code failure.

Unverified with real authenticated users: two Clerk sessions and refreshes; owner photo upload and public delivery; profile edits and parameter preference persistence; HTTP unauthorized reads of evidence, resource constraints, strategy trials and private activity; real network failure and stale-cache recovery; desktop/mobile signed-in screenshots. No real-user screenshots are attached. Earlier screenshots in this report are mocked browser fixtures only. Offset pagination under concurrent publication remains a known consistency limitation; no cursor pagination was implemented without a demonstrated material real-user defect.

The exact prerequisites to complete acceptance are two genuine Clerk test accounts able to sign into a deployment of PR #37's code, with that deployment wired to an isolated PostgreSQL database and private photo storage. The tests must then perform the specified two-session browser/API journey and capture authenticated network and persistence evidence. Existing production accounts and data must remain untouched.

PostgreSQL pagination characterization: publishing a new market between offset page requests repeated the previously fetched ID on the next page (2/2 integration tests passed after this addition). The frontend deduplicates visible cards, but an in-flight sequence can miss the new item until search/sort reset or refresh. This is a fresh-feed consistency limitation; it did not expose private data. No cursor change was made in this acceptance-only pass. Combined PostgreSQL selection: 7/7 passed.
