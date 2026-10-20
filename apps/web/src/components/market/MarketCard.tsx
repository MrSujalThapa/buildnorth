import type { Market } from "../../adapters/templateTypes";

import WealthsimpleAreaChart from "./WealthsimpleAreaChart";

type Props = {
  market: Market;
  onClick: () => void;
  selectMode?: boolean;
  selected?: boolean;
};

function signedPercent(
  value: number,
) {
  return `${
    value >= 0 ? "+" : ""
  }${value.toFixed(1)}%`;
}

export default function MarketCard({
  market,
  onClick,
  selectMode = false,
  selected = false,
}: Props) {
  return (
    <button
      type="button"
      className={`market-card${selectMode ? " is-selectable" : ""}${selected ? " is-selected" : ""}`}
      onClick={onClick}
      aria-pressed={selectMode ? selected : undefined}
    >
      <div className="market-card-header">
        <div className="market-card-title-block">
          <div className="market-card-category">
            {market.category}
          </div>

          <h2>
            {market.title}
          </h2>
        </div>

        <div className="market-card-odds">
          {market.historyUnavailable || market.odds === null
            ? "—"
            : `${market.odds.toFixed(
                0,
              )}%`}
        </div>
      </div>

      <div
        className={`market-card-return ${
          (market.todayReturn ?? 0) >= 0
            ? "positive"
            : "negative"
        }`}
      >
        {market.todayReturn == null
          ? "— today"
          : `${signedPercent(market.todayReturn)} today`}
      </div>

      <div className="market-card-chart">
        {market.historyUnavailable ? (
          <div className="unpriced-state">
            <strong>History unavailable</strong>
            <span>Could not load published forecast history.</span>
          </div>
        ) : (
          <WealthsimpleAreaChart
            data={
              market.history
            }
            interactive={
              false
            }
          />
        )}
      </div>
    </button>
  );
}
