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
      {selectMode ? <span className="selection-indicator" aria-hidden="true">{selected ? "✓" : ""}</span> : null}
      <div className="market-card-header">
        <div className="market-card-title-block">
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
          ? "—"
          : `${signedPercent(market.todayReturn)} today`}
      </div>

      <div className={`market-card-chart${market.historyUnavailable || !market.history.length ? " is-empty" : ""}`}>
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
