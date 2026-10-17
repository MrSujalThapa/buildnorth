from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from personal_markets.what_if.domain import SimulationConfig, SimulationDiagnostics


@dataclass(frozen=True, slots=True)
class PairedSimulation:
    baseline_success: np.ndarray
    scenario_success: np.ndarray
    baseline_outcome: np.ndarray
    scenario_outcome: np.ndarray
    scenario_trajectory: np.ndarray
    execution: np.ndarray
    diagnostics: SimulationDiagnostics


class SimulationEngine:
    version = "1.0.0"

    def continuous_target(
        self,
        *,
        current_value: float,
        target_value: float,
        periods: int,
        direction: str,
        flow: float,
        growth_mean: float,
        growth_volatility: float,
        shock_probability: float,
        shock_fraction: float,
        execution_probability: float,
        intervention_effect: float,
        config: SimulationConfig,
        scenario_flow: float | None = None,
        scenario_growth_mean: float | None = None,
        scenario_growth_volatility: float | None = None,
        scenario_shock_probability: float | None = None,
        scenario_shock_fraction: float | None = None,
    ) -> PairedSimulation:
        """Paired baseline/scenario paths under common random numbers.

        An action can reach the model two ways: as an additive ``intervention_effect``, or
        as a different value for a state variable the transition already consumes (a
        larger monthly contribution is literally ``flow``). Both must be gated on whether
        the user actually executes, otherwise the scenario arm reports the
        fully-executed probability while claiming to be the realistic one.

        Scenario state defaults to the baseline value, so callers that only pass an
        intervention effect are unaffected.
        """
        started = perf_counter()
        scenario_flow = flow if scenario_flow is None else scenario_flow
        scenario_growth_mean = (
            growth_mean if scenario_growth_mean is None else scenario_growth_mean
        )
        scenario_growth_volatility = (
            growth_volatility
            if scenario_growth_volatility is None
            else scenario_growth_volatility
        )
        scenario_shock_probability = (
            shock_probability
            if scenario_shock_probability is None
            else scenario_shock_probability
        )
        scenario_shock_fraction = (
            shock_fraction if scenario_shock_fraction is None else scenario_shock_fraction
        )
        rng = np.random.default_rng(config.seed)
        baseline_parts: list[np.ndarray] = []
        scenario_parts: list[np.ndarray] = []
        execution_parts: list[np.ndarray] = []
        baseline_success_parts: list[np.ndarray] = []
        scenario_success_parts: list[np.ndarray] = []
        scenario_trajectory_parts: list[np.ndarray] = []
        converged = False
        n_draws = 0

        while n_draws < config.maximum_draws:
            batch = min(config.batch_draws, config.maximum_draws - n_draws)
            noise = rng.standard_t(df=5, size=(batch, periods))
            uniforms = rng.random((batch, periods))
            execution = rng.random(batch) < execution_probability
            executed = execution.astype(float)[:, None]

            scale = np.sqrt(5 / 3)
            returns = growth_mean + noise * growth_volatility / scale
            shocks = uniforms < shock_probability
            # Unexecuted paths keep the baseline state, so the scenario arm is the
            # execution-weighted mixture rather than the fully-executed arm.
            path_growth_mean = growth_mean + (scenario_growth_mean - growth_mean) * executed
            path_growth_volatility = (
                growth_volatility + (scenario_growth_volatility - growth_volatility) * executed
            )
            path_shock_probability = (
                shock_probability + (scenario_shock_probability - shock_probability) * executed
            )
            path_shock_fraction = (
                shock_fraction + (scenario_shock_fraction - shock_fraction) * executed[:, 0]
            )
            path_flow = flow + (scenario_flow - flow) * executed[:, 0]
            scenario_returns = path_growth_mean + noise * path_growth_volatility / scale
            scenario_shocks = uniforms < path_shock_probability

            baseline = np.full(batch, current_value, dtype=float)
            scenario = baseline.copy()
            scenario_trajectory = np.empty((batch, periods + 1), dtype=float)
            scenario_trajectory[:, 0] = scenario
            for period in range(periods):
                baseline_shock = np.where(shocks[:, period], shock_fraction, 0.0)
                baseline = baseline * (1 + returns[:, period] - baseline_shock) + flow
                scenario_shock = np.where(scenario_shocks[:, period], path_shock_fraction, 0.0)
                scenario = (
                    scenario * (1 + scenario_returns[:, period] - scenario_shock) + path_flow
                )
                scenario += intervention_effect * execution
                scenario_trajectory[:, period + 1] = scenario
            baseline_success = (
                baseline >= target_value if direction == "at_least" else baseline <= target_value
            )
            scenario_success = (
                scenario >= target_value if direction == "at_least" else scenario <= target_value
            )
            baseline_parts.append(baseline)
            scenario_parts.append(scenario)
            execution_parts.append(execution)
            baseline_success_parts.append(baseline_success)
            scenario_success_parts.append(scenario_success)
            scenario_trajectory_parts.append(scenario_trajectory)
            n_draws += batch
            scenario_all = np.concatenate(scenario_success_parts)
            probability = float(np.mean(scenario_all))
            error = float(np.sqrt(probability * (1 - probability) / n_draws))
            if n_draws >= config.minimum_draws and error <= config.probability_se_tolerance:
                converged = True
                break

        baseline_success_all = np.concatenate(baseline_success_parts)
        scenario_success_all = np.concatenate(scenario_success_parts)
        probability = float(np.mean(scenario_success_all))
        error = float(np.sqrt(probability * (1 - probability) / n_draws))
        return PairedSimulation(
            baseline_success=baseline_success_all,
            scenario_success=scenario_success_all,
            baseline_outcome=np.concatenate(baseline_parts),
            scenario_outcome=np.concatenate(scenario_parts),
            scenario_trajectory=np.concatenate(scenario_trajectory_parts),
            execution=np.concatenate(execution_parts),
            diagnostics=SimulationDiagnostics(
                n_draws=n_draws,
                seed=config.seed,
                converged=converged,
                criterion=f"MC SE <= {config.probability_se_tolerance}",
                achieved_mc_error=error,
                duration_ms=(perf_counter() - started) * 1000,
            ),
        )

    def deadline_event(
        self,
        *,
        baseline_probability: float,
        scenario_probability: float,
        periods: int,
        execution_probability: float,
        config: SimulationConfig,
    ) -> PairedSimulation:
        started = perf_counter()
        rng = np.random.default_rng(config.seed)
        n_draws = config.minimum_draws
        execution = rng.random(n_draws) < execution_probability
        baseline_success = rng.random(n_draws) < baseline_probability
        scenario_base = rng.random(n_draws) < scenario_probability
        uplift = max(0.0, scenario_probability - baseline_probability)
        scenario_success = np.where(
            execution,
            np.minimum(1.0, scenario_base.astype(float) + uplift * execution.astype(float)),
            scenario_base,
        ).astype(bool)
        trajectory = np.tile(
            np.linspace(baseline_probability, scenario_probability, periods + 1),
            (n_draws, 1),
        )
        error = float(
            np.sqrt(scenario_probability * (1 - scenario_probability) / max(n_draws, 1))
        )
        return PairedSimulation(
            baseline_success=baseline_success,
            scenario_success=scenario_success,
            baseline_outcome=np.full(n_draws, baseline_probability),
            scenario_outcome=np.full(n_draws, scenario_probability),
            scenario_trajectory=trajectory,
            execution=execution,
            diagnostics=SimulationDiagnostics(
                n_draws=n_draws,
                seed=config.seed,
                converged=True,
                criterion=f"MC SE <= {config.probability_se_tolerance}",
                achieved_mc_error=error,
                duration_ms=(perf_counter() - started) * 1000,
            ),
        )
