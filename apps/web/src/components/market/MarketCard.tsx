import type { Market } from "../../adapters/templateTypes";

import WealthsimpleAreaChart from "./WealthsimpleAreaChart";

type Props = {
  market: Market;
  onClick: () => void;
  selectMode?: boolean;
  selected?: boolean;
};

function signedPointChange(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)} pp`;
}

function age(at: number) {
  const days = Math.floor((Date.now() - at) / 86_400_000);
  return days < 1 ? "today" : `${days}d ago`;
}

function changeLabel(market: Market): { text: string; change: number | null } {
  if (market.todayReturn != null) {
    return { text: `${signedPointChange(market.todayReturn)} today`, change: market.todayReturn };
  }
  if (market.lastRevision) {
    const { change, at } = market.lastRevision;
    return { text: `${signedPointChange(change)} · ${age(at)}`, change };
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
          {market.historyUnavailable || market.odds === null
            ? "—"
            : `${market.odds.toFixed(
                0,
              )}%`}
        </div>
      </div>

      <div
        className={`market-card-return ${
          movement.change == null ? "" : movement.change >= 0 ? "positive" : "negative"
        }`}
        title={movement.change == null ? undefined : "Change at the most recent model revision"}
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
