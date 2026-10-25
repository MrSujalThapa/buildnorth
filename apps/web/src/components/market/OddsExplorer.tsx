import { useMemo, useState } from "react";

import type { ChartMarker, ChartPoint } from "../../adapters/templateTypes";
import {
  filterHistoryForRange,
  type MarketRange,
} from "./marketRanges";
import WealthsimpleAreaChart, {
  type ChartSelection,
} from "./WealthsimpleAreaChart";

type Props = {
  history: ChartPoint[];
  ranges: MarketRange[];
  markers?: ChartMarker[];
  comparison?: ChartPoint | null;
  overlay?: ChartPoint[];
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
  emptyMessage = "No published forecast yet. Play It Out will not invent a series.",
  interactive = true,
  initialRange,
  onSelectionChange,
}: Props) {
  const [selectedRange, setSelectedRange] = useState<MarketRange | null>(null);
  const activeRange = selectedRange ?? initialRange ?? ranges[Math.min(2, Math.max(ranges.length - 1, 0))];
  const chartData = useMemo(
    () => (activeRange ? filterHistoryForRange(history, activeRange) : history),
    [activeRange, history],
  );

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
      <div className="chart-help">Press and drag across the chart to compare odds.</div>
    </section>
  );
}
