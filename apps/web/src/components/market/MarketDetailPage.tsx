import { useMemo, useState } from "react";
import {
  ArrowLeft,
  Bell,
  BookOpen,
  Code2,
  Rocket,
  Star,
  Users,
  X,
} from "lucide-react";

import type { Market, MarketEvent } from "../../adapters/templateTypes";
import { ODDS_EXPLORER_RANGES } from "./marketRanges";
import OddsExplorer from "./OddsExplorer";
import {
  type ChartSelection,
} from "./WealthsimpleAreaChart";
import "./market-detail.css";

type Props = {
  market: Market;
  criticDecision?: string | null;
  onBack: () => void;
  onWhatIf: () => void;
  onEvidence?: () => void;
};

function EventIcon({ event }: { event: MarketEvent }) {
  const props = { size: 19, strokeWidth: 1.9 };

  switch (event.icon) {
    case "code":
      return <Code2 {...props} />;
    case "x":
      return <X {...props} />;
    case "rocket":
      return <Rocket {...props} />;
    case "people":
      return <Users {...props} />;
    case "book":
      return <BookOpen {...props} />;
  }
}

function signedPercent(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function signedPoints(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)} pts`;
}

function formatPointDate(timestamp: number) {
  return new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function formatRangeDate(start: number, end: number) {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const sameDay =
    startDate.getFullYear() === endDate.getFullYear() &&
    startDate.getMonth() === endDate.getMonth() &&
    startDate.getDate() === endDate.getDate();

  if (sameDay) {
    const day = new Intl.DateTimeFormat("en-CA", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    const time = new Intl.DateTimeFormat("en-CA", {
      hour: "numeric",
      minute: "2-digit",
    });

    return `${day.format(startDate)} · ${time.format(startDate)} – ${time.format(endDate)}`;
  }

  const formatter = new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  return `${formatter.format(startDate)} – ${formatter.format(endDate)}`;
}

export default function MarketDetailPage({
  market,
  criticDecision,
  onBack,
  onWhatIf,
  onEvidence,
}: Props) {
  const ranges = ODDS_EXPLORER_RANGES;
  const [chartSelection, setChartSelection] = useState<ChartSelection | null>(null);
  const markers = useMemo(
    () =>
      market.events
        .filter((event) => typeof event.timestamp === "number")
        .map((event) => ({ timestamp: event.timestamp as number, label: event.label })),
    [market.events],
  );
  const singlePointSelection =
    chartSelection &&
    chartSelection.start.timestamp === chartSelection.end.timestamp;

  return (
    <main className="market-page">
      <section className="market-shell">
        <header className="market-topbar">
          <button
            className="icon-btn"
            type="button"
            aria-label="Go back"
            onClick={onBack}
          >
            <ArrowLeft size={27} strokeWidth={1.8} />
          </button>

          <div className="market-topbar-actions">
            <button className="icon-btn" type="button" aria-label="Watch market">
              <Star size={26} strokeWidth={1.8} />
            </button>
            <button className="icon-btn" type="button" aria-label="Market alerts">
              <Bell size={26} strokeWidth={1.8} />
            </button>
          </div>
        </header>

        <div className="market-heading">
          <div className="market-eyebrow">{market.category}</div>
          <h1>{market.title}</h1>
          <p className="market-meta">{market.meta}</p>
        </div>

        <section className="market-quote">
          {chartSelection ? (
            singlePointSelection ? (
              <>
                <div className="market-price">{chartSelection.end.value.toFixed(1)}%</div>
                <div className="market-price-hint">
                  {formatPointDate(chartSelection.end.timestamp)}
                </div>
              </>
            ) : (
              <>
                <div className="selection-date">
                  {formatRangeDate(
                    chartSelection.start.timestamp,
                    chartSelection.end.timestamp,
                  )}
                </div>
                <div className="selection-odds">
                  {chartSelection.start.value.toFixed(1)}%
                  <span>→</span>
                  {chartSelection.end.value.toFixed(1)}%
                </div>
                <div className="selection-change-row">
                  <span
                    className={chartSelection.pointChange >= 0 ? "positive" : "negative"}
                  >
                    {signedPoints(chartSelection.pointChange)}
                  </span>
                  <span
                    className={chartSelection.percentChange >= 0 ? "positive" : "negative"}
                  >
                    {signedPercent(chartSelection.percentChange)}
                  </span>
                </div>
              </>
            )
          ) : criticDecision === "withhold" ? (
            <>
              <div className="market-price" data-testid="goal-price">Withheld</div>
              <div className="market-price-hint">Forecast withheld by critic.</div>
            </>
          ) : market.odds === null ? (
            <>
              <div className="market-price" data-testid="goal-price">Not priced</div>
              <div className="market-price-hint">
                {market.unpricedReason ?? "Odds are still forming."}
              </div>
            </>
          ) : (
            <>
              <div className="market-price" data-testid="goal-price">{market.odds.toFixed(1)}%</div>
              <div className="market-price-hint">Current modeled odds</div>
            </>
          )}
        </section>

        <OddsExplorer
          history={market.history}
          ranges={ranges}
          markers={markers}
          onSelectionChange={setChartSelection}
        />

        {market.modelExplanation ? (
          <section className="market-section model-note">
            <h2>Model</h2>
            <p>{market.modelExplanation}</p>
          </section>
        ) : null}

        <section className="market-section recent-events">
          <h2>Recent events</h2>
          <div className="event-list">
            {market.events.map((event) => {
              const unknown = event.impact == null;
              const positive = (event.impact ?? 0) >= 0;

              return (
                <div className="event-row" key={event.id}>
                  <div className={`event-icon ${unknown ? "" : positive ? "positive" : "negative"}`.trim()}>
                    <EventIcon event={event} />
                  </div>
                  <div className="event-main">
                    <div className="event-label">{event.label}</div>
                    <div className="event-time">{event.occurredAt}</div>
                  </div>
                  <div className={`event-impact ${unknown ? "" : positive ? "positive" : "negative"}`.trim()}>
                    {event.impact == null ? "—" : `${signedPercent(event.impact)} odds`}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="return-panel">
          <div className="return-stat">
            <div className="return-label">Today's return</div>
            <div className={`return-value ${(market.todayReturn ?? 0) >= 0 ? "positive" : "negative"}`}>
              {market.todayReturn == null ? "—" : signedPercent(market.todayReturn)}
            </div>
          </div>

          <div className="return-divider" />

          <div className="return-stat">
            <div className="return-label">Total return</div>
            <div className={`return-value ${(market.totalReturn ?? 0) >= 0 ? "positive" : "negative"}`}>
              {market.totalReturn == null ? "—" : signedPercent(market.totalReturn)}
            </div>
          </div>
        </section>

        <div className="market-actions">
          <button className="primary-action" type="button" onClick={onWhatIf}>
            What if
          </button>
          <button className="secondary-action" type="button" onClick={onEvidence}>
            Evidence
          </button>
        </div>
      </section>
    </main>
  );
}
