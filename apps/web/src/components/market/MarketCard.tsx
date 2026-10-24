import type { Market } from "../../adapters/templateTypes";

import WealthsimpleAreaChart from "./WealthsimpleAreaChart";
import { chartPointChange, chartTrend } from "./chartTrend";

type Props = {
  market: Market;
  onClick: () => void;
  selectMode?: boolean;
  selected?: boolean;
};

function signedPointChange(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)} pp`;
}

function changeLabel(market: Market): { text: string; change: number | null } {
  if (market.currentForecastStatus && market.currentForecastStatus !== "published") {
    return { text: "Historical forecast shown", change: null };
  }
  if (!market.historyUnavailable) {
    const change = chartPointChange(market.history);
    if (change != null) return { text: `${signedPointChange(change)} shown`, change };
  }
  return { text: "—", change: null };
}

export default function MarketCard({
  market,
  onClick,
  selectMode = false,
  selected = false,
}: Props) {
  const movement = changeLabel(market);
  return (
    <button
      type="button"
      className={`market-card${selectMode ? " is-selectable" : ""}${selected ? " is-selected" : ""}`}
      onClick={onClick}
      aria-pressed={selectMode ? selected : undefined}
    >
      {selectMode ? <span className="selection-indicator" aria-hidden="true">{selected ? "✓" : ""}</span> : null}
      <div className="market-card-header">
        <div className="market-card-title-block">
          <h2>
            {market.title}
          </h2>
        </div>

        <div className="market-card-odds">
          {market.currentForecastStatus === "withheld" ? "Withheld"
            : market.currentForecastStatus === "evidence_pending" ? "Pending"
            : market.currentForecastStatus === "evidence_failed" ? "Evidence failed"
            : market.historyUnavailable || market.odds === null
            ? "—"
            : `${market.odds.toFixed(
                0,
              )}%`}
        </div>
      </div>

      <div
        className={`market-card-return ${market.historyUnavailable || market.currentForecastStatus !== "published" ? "neutral" : chartTrend(market.history)}`}
        title={movement.change == null ? undefined : "Change across the displayed forecast history"}
      >
        {movement.text}
      </div>

      <div className={`market-card-chart${market.historyUnavailable || !market.history.length ? " is-empty" : market.history.length === 1 ? " is-sparse" : ""}`}>
        {!market.historyUnavailable && market.history.length ? (
          <WealthsimpleAreaChart
            data={
              market.history
            }
            interactive={
              false
            }
          />
        ) : null}
      </div>
    </button>
  );
}
