import { useMemo, useState } from "react";

import type { ChartMarker, ChartPoint } from "../../adapters/templateTypes";
import {
  rangeWindow,
  type MarketRange,
} from "./marketRanges";
import WealthsimpleAreaChart, {
  type ChartSelection,
  type ScenarioBranch,
} from "./WealthsimpleAreaChart";

type Props = {
  history: ChartPoint[];
  ranges: MarketRange[];
  markers?: ChartMarker[];
  comparison?: ChartPoint | null;
  overlay?: ChartPoint[];
  overlayTone?: "positive" | "negative";
  scenarioBranch?: ScenarioBranch | null;
  showTimeAxis?: boolean;
  emptyMessage?: string;
  interactive?: boolean;
  initialRange?: MarketRange;
  onSelectionChange?: (selection: ChartSelection | null) => void;
};

export default function OddsExplorer({
  history,
  ranges,
  markers = [],
  comparison = null,
  overlay = [],
  overlayTone,
  scenarioBranch = null,
  showTimeAxis = false,
  emptyMessage = "No published forecast yet. Play It Out will not invent a series.",
  interactive = true,
  initialRange,
  onSelectionChange,
}: Props) {
  const [selectedRange, setSelectedRange] = useState<MarketRange | null>(null);
  const activeRange = selectedRange ?? initialRange ?? ranges[Math.min(2, Math.max(ranges.length - 1, 0))];
  const rangeView = useMemo(
    () => (activeRange ? rangeWindow(history, activeRange) : null),
    [activeRange, history],
  );
  const chartData = rangeView?.points ?? history;
  const standingNote =
    rangeView && activeRange && activeRange.unit !== "all" && rangeView.updates === 0 && rangeView.points.length
      ? `No updates in the last ${activeRange.label}. Holding the standing forecast of ${Math.round(rangeView.points[0]!.value)}%${rangeView.standing ? ` from ${new Date(rangeView.standing.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" })}` : ""}.`
      : null;

  function selectRange(range: MarketRange) {
    setSelectedRange(range);
    onSelectionChange?.(null);
  }

  if (history.length === 0) {
    return (
      <section className="market-chart-section">
        <div className="market-chart-wrapper odds-empty" role="status">
          <strong>No published odds</strong>
          <span>{emptyMessage}</span>
        </div>
      </section>
    );
  }

  return (
    <section className="market-chart-section">
      <div className="market-chart-wrapper">
        <WealthsimpleAreaChart
          data={chartData}
          overlay={overlay}
          overlayTone={overlayTone}
          scenarioBranch={scenarioBranch}
          showTimeAxis={showTimeAxis}
          markers={markers}
          comparison={comparison}
          interactive={interactive}
          onSelectionChange={onSelectionChange}
        />
      </div>
      <div className="range-control" aria-label="Chart range">
        {ranges.map((range) => (
          <button
            key={range.label}
            type="button"
            className={activeRange?.label === range.label ? "selected" : ""}
            onClick={() => selectRange(range)}
          >
            {range.label}
          </button>
        ))}
      </div>
      {standingNote ? <p className="chart-standing-note" role="status">{standingNote}</p> : null}
      <div className="chart-help">Press and drag across the chart to compare odds.</div>
    </section>
  );
}
