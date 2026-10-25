# What If visual source inventory

Base: PR #34 head `77d8758`; PR #38 `4712b98` was read only. This branch does
not merge either PR into the other.

| Mode | Simple website presentation | Deeper website presentation | Backend operation |
| --- | --- | --- | --- |
| Change | `ImpactWorkspace` uses `OddsExplorer` for immutable published history plus a hypothetical branch, and odds/percentage-point cards. | The same `ImpactWorkspace` uses `OutcomeDistribution`, sensitivity bars, and `OutcomeRangeChart` only when returned bins and fan points exist. | `fast_reprice`; configuration differs by depth (`minimum_draws` 2000/8000, `maximum_draws` 4000/20000, sensitivity false/true). |
| Futures | `PossibleFuturesView` uses the backend scenario distribution, family bars and selection. | The same component uses `OutcomeIntervals` for non-event quantiles, scenario-family selection, and provenance. | `parse_decision`, `parse_intervention`, then `possible_futures`. |
| Compare | `CompareOptionsView` uses modeled option strips and `OutcomeIntervals`. | The same component shows option visibility and `OutcomeIntervals` overlap with comparative odds. | `compare_paths`; custom alternatives pass through `parse_intervention`. |
| Reverse | `PathsToGoalView` shows ranked feasible paths and editable target. | The same component uses `SimulationCloud` scatter/frontier, selected path and constraints. | `target_search` with depth-specific base config. |

The four mode components are already data-driven. `WhatIfPage` is coupled to
website state and `useWhatIfSimulation`; it is not a safe MCP entry point.
The mode components and the website adapters (`previewFromResult`,
`toImpactViewModel`, `futuresFromDistribution`, `toCompareOptions`,
`toPathStrategies`) are the intended shared rendering boundary. Browser-only
navigation, evidence writes and persistence controls remain outside it.

PR #38's existing `Odds Explorer` MCP Apps resource and PNG are historical-chart
implementations. They are not substitutes for these four What If components.
Its notification guards and owner-bound MCP response design should be carried
into later integration. Current backend Docker builds only Python assets; a
React MCP bundle and Chromium image renderer require an explicit build/runtime
change, not a dynamic public URL containing private results.
