# Pass 9B strategy learning

The strategy-learning module is separate from behavior execution probability, the Profile
radar, evidence ingestion, forecast publication, and What If. The existing commitment
trials estimate whether an action will be executed. This module records which actions
were recommended, attempted, and followed by measured progress. It does not infer
causation or produce odds.

## Ontology and contracts

`GoalContract` → optional `milestone_key` → extensible `strategy_key` →
`RecommendationTrial` → decision/attempt → existing `evidence_events` IDs →
`OutcomeObservation` (`intermediate` or `final`). Goal milestones are not yet a
standalone table, so `milestone_key` names a goal-specific state dimension or milestone
without inventing a foreign key. Outcome observations are versioned by append-only
rows. The latest observation at a requested `as_of` forms the learning context.

`strategy_recommendations` records owner, goal, grounded context, assumptions, prompt
checksum/version, provider/model/request ID, expected metric/unit/direction/target,
horizon, and pending/accepted/declined/ignored feedback. `strategy_outcome_observations`
records attempted state, intermediate/final outcome, confidence, provenance, observed
time, and pending/successful/unsuccessful/inconclusive/insufficient evidence status.
`strategy_outcome_evidence` links existing evidence IDs, never copies evidence payloads.
The database enforces goal and evidence ownership through composite foreign keys.

The service boundary is `StrategyLearningService.recommend`, `feedback`,
`record_outcome`, `learning_context`, and `get_recommendation`. Pass 9A can call these
methods after its own authorization and evidence validation. The authenticated API
offers `GET/POST /api/v1/goals/{goal_id}/strategy-recommendations`, plus feedback and
outcome POST endpoints on an individual recommendation. GET is a pollable inbox;
generation is explicit and may incur the existing inference-provider charge.
The API never accepts client-declared external research or relationship facts.

Recommendation prompts include goal, owner-scoped active evidence, deadline, direct
metric gaps, constraints, permitted facts, and up to 30 prior strategy outcomes. The
API's progress snapshot is assembled from existing evidence rows and remains labeled
as observations, not a fabricated aggregate. The deterministic validator rejects
unlisted fact IDs, citations or relationships, future-dated context, and claimed
numeric odds. Prose claim verification is limited; user-entered facts remain
self-reported, and external research must be retrieved through a trusted future path.
The existing structured inference router handles owner-scoped provider selection,
billing, validation, and bounded retries. An unchanged pending recommendation is
reused before another inference call; the database fingerprint also deduplicates a
repeated action and horizon. Concurrent first requests may still both call inference
before the unique database write resolves. There is no new provider.

Outcome classification requires a recorded attempt and active, owner-and-goal-scoped,
non-synthetic evidence observed after the recommendation for a successful or
unsuccessful comparison against an explicit target. The linked evidence must match
the expected metric, unit, and reported numeric value as a typed snapshot. An
incremental activity event cannot by itself establish a cumulative outcome.
Final successful or unsuccessful outcomes additionally require evidence with
`verified_outcome` provenance; existing self-reports and provider activity do not
qualify. They remain inconclusive until an outcome-verification path exists.
Missing activity does not mean failure. Results without a target or validating
evidence are inconclusive or insufficient. If linked evidence is later retracted,
the immutable observation remains for audit while the retrieved learning context
reports it as inconclusive. A later observation is associated with a strategy but
is not asserted to be caused by it. No forecast is automatically changed.

Reviewed public marketplace blueprints can later enter through the optional
`ReviewedBlueprintSource` interface; this branch does not depend on PR #33.

## Offline evaluation

`uv run python scripts/evaluate_strategy_learning.py` reproduces
`benchmarks/strategy_learning_v1/results.json`. This fixture has 400 synthetic users
and two explicit 30-day binary intermediate-outcome contracts: career interviews and
education practice sessions. The reference is train-set goal-family prevalence. The
candidate is logistic regression on goal family, strategy type and prior dated outcomes.
Only history observed before a recommendation enters its features. Users are assigned
by stable hash to train, validation and test (247/73/80); no user spans partitions.
Unconsented authentic rows and unsupported goal/outcome contracts are excluded.

On the fixed synthetic test partition (80 users), reference/candidate Brier is
0.221679/0.204225, log loss 0.635602/0.598781, and ECE-10 0.047438/0.081008.
The Brier gain is a property of this generator, **not evidence of production
improvement**. Calibration worsens. No production retraining or consented population
export runs here. Real-data evaluation needs consented comparable outcome contracts,
enough resolved users, explicit confounding analysis, and a frozen holdout before
shipping a model update.

## Scope and known limits

No proactive schedule or push notifications are attached yet. Consumers call the
service or poll the inbox. The trusted context adapter reads the goal's existing
active evidence and marks missing direct metric records; it does not compute
unsupported cumulative progress or validate user-entered facts as provider evidence.
No real provider inference was run or charged in this pass. An optional Era evaluation
was not attempted because authentic outcome data is insufficient.
