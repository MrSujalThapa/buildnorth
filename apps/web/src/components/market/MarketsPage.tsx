import type { Market } from "../../adapters/templateTypes";
import MarketCard from "./MarketCard";
import "./markets.css";

type Props = {
  markets: Market[];
  onSelectMarket: (marketId: string) => void;
};

export default function MarketsPage({ markets, onSelectMarket }: Props) {
  return (
    <main className="markets-page">
      <section className="markets-shell">
        <header className="markets-header">
          <div className="markets-eyebrow">
            MARKETS
          </div>

          <h1>
            Your outcomes
          </h1>

          <p>
            Track how new evidence
            changes the odds of the
            things you care about.
          </p>
        </header>

        <div className="markets-grid">
          {markets.length === 0 ? (
            <div className="unpriced-state" role="status">
              <strong>No goals yet</strong>
              <span>Create a goal to start tracking outcome odds.</span>
            </div>
          ) : (
            markets.map((market) => (
              <MarketCard
                key={market.id}
                market={market}
                onClick={() => onSelectMarket(market.id)}
              />
            ))
          )}
        </div>
      </section>
    </main>
  );
}
