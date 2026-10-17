import type { Market } from "../../adapters/templateTypes";

import WealthsimpleAreaChart from "./WealthsimpleAreaChart";

type Props = {
  market: Market;
  onClick: () => void;
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
}: Props) {
  return (
    <button
      type="button"
      className="market-card"
      onClick={onClick}
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
          {market.odds === null
            ? "ΓÇö"
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
        <WealthsimpleAreaChart
          data={
            market.history
          }
          interactive={
            false
          }
        />
      </div>
    </button>
  );
}
