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

Additional correctness fix: public history now accepts only `published_forecast` rows, excluding synthetic and hypothetical source kinds. Public market opens at All history to avoid a nearly empty default month when authentic history is sparse. The chart still draws an awkward right-edge spike with the two-point fixture; chart rendering and sparse-history treatment warrant a separate visual pass before shipping.

## Consumer journey review

- **Search/sort:** query and sort reach the public-market API. Only the first page is rendered; no pagination or result count. Fixture browser navigation passes; real database sorting/search performance not measured.
- **Follow/star:** authenticated backend endpoints and idempotent repeat actions pass isolated HTTP tests. The UI now reports failures and refetches relevant counters. A live two-Clerk-user journey has not run.
- **Publish/unpublish:** owner-scoped API test passes and hidden market disappears after unpublish. The public heatmap now hides its events too. Production propagation/cache behavior remains unverified.
- **Fork:** isolated API test shows a private goal owned by the visitor, idempotent retry, and no copied odds/evidence. Sanitized contract and personal-resource checks added. Real database transaction and creation UX still need deployment proof.
- **Profiles:** own editing, photo crop/upload mock, measured-parameter selection and refresh persistence pass browser fixture tests. The public profile shows activity and public markets; private radar is absent. Actual photo persistence and public delivery with signed-in users remain unverified.
- **Heatmap:** counts represent recorded social events, not all productivity across integrations. The public/private filtering is fixed, but its title should eventually explain the event scope. Narrow view scrolls horizontally; month labels remain dense.
- **Charts:** real API history is passed through, with no invented points. The sparse-history fixture produces a conspicuous right-edge line; this is a visual defect, not a probability calculation defect.
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
