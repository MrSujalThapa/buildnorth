import { useId, useRef, useState } from "react";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ChartMarker, ChartPoint } from "../../adapters/templateTypes";

import "./wealthsimple-chart.css";
import { chartTrend } from "./chartTrend";

export type ChartSelection = {
  start: ChartPoint;
  end: ChartPoint;

  pointChange: number;
  percentChange: number;
};

export type ScenarioBranch = {
  comparisonBaseline: number;
  scenarioOdds: number;
  tone: "positive" | "negative";
};

/**
 * A probability series drawn on the same axes as the published history.
 * With `points` the series is plotted as given. Without them it is anchored at the
 * end of the published history and runs from `start` to `end` across the scenario
 * region, which represents a single terminal probability rather than a modeled path.
 */
export type ProbabilityBranch = {
  id: string;
  label: string;
  color: string;
  points?: ChartPoint[];
  start?: number;
  end?: number;
  dashed?: boolean;
  /** Shown next to the value in the legend, e.g. "+6.7 pts". */
  note?: string;
};

type Props = {
  data: ChartPoint[];
  overlay?: ChartPoint[];
  overlayTone?: "positive" | "negative";
  scenarioBranch?: ScenarioBranch | null;
  branches?: ProbabilityBranch[];
  /** Name and color of the published-history series when branches are shown. */
  historyLabel?: string;
  historyColor?: string;
  lineOnly?: boolean;
  percentAxis?: boolean;
  highlightedBranchId?: string | null;
  onBranchSelect?: (id: string) => void;
  xTicks?: { value: number; label: string }[];
  scenarioRegionLabel?: string;
  showTimeAxis?: boolean;
  markers?: ChartMarker[];
  comparison?: ChartPoint | null;
  interactive?: boolean;
  onSelectionChange?: (selection: ChartSelection | null) => void;
};

const PLOT_MARGIN = { top: 12, bottom: 0, left: 4 };
const PERCENT_AXIS_WIDTH = 40;
const SCENARIO_REGION_SHARE = 0.28;

function nearestPointIndex(data: ChartPoint[], targetTimestamp: number) {
  const first = data[0];
  if (!first) return -1;
  let bestIndex = 0;
  let bestDistance = Math.abs(first.timestamp - targetTimestamp);
  for (let index = 1; index < data.length; index += 1) {
    const point = data[index];
    if (!point) continue;
    const distance = Math.abs(point.timestamp - targetTimestamp);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  }
  return bestIndex;
}

function stepValueAt(data: ChartPoint[], timestamp: number): number | null {
  let value: number | null = null;
  for (const point of data) {
    if (point.timestamp > timestamp) break;
    value = point.value;
  }
  return value;
}

function linearValueAt(points: ChartPoint[], timestamp: number): number | null {
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1]!;
    const b = points[index]!;
    if (timestamp >= a.timestamp && timestamp <= b.timestamp) {
      const span = b.timestamp - a.timestamp;
      return span <= 0 ? b.value : a.value + ((b.value - a.value) * (timestamp - a.timestamp)) / span;
    }
  }
  return null;
}

function percentDomain(values: number[]): { domain: [number, number]; ticks: number[] } {
  const lo = Math.max(0, Math.floor((Math.min(...values) - 4) / 10) * 10);
  const hi = Math.min(100, Math.ceil((Math.max(...values) + 4) / 10) * 10);
  const step = hi - lo > 50 ? 20 : 10;
  const ticks: number[] = [];
  for (let tick = lo; tick <= hi; tick += step) ticks.push(tick);
  return { domain: [lo, Math.max(hi, lo + 10)], ticks };
}

function formatPercent(value: number): string {
  return `${Number(value.toFixed(1))}%`;
}

export default function WealthsimpleAreaChart({
  data,
  overlay = [],
  overlayTone = "positive",
  scenarioBranch = null,
  branches = [],
  historyLabel = "Published forecast",
  historyColor,
  lineOnly = false,
  percentAxis = false,
  highlightedBranchId = null,
  onBranchSelect,
  xTicks,
  scenarioRegionLabel,
  showTimeAxis = false,
  markers = [],
  comparison = null,
  interactive = true,
  onSelectionChange,
}: Props) {
  const rawId = useId();
  const gradientId = `ws-gradient-${rawId.replace(/:/g, "")}`;
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef(false);
  const [selection, setSelection] = useState<{ startIndex: number; endIndex: number } | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [hoverTimestamp, setHoverTimestamp] = useState<number | null>(null);

  const multiSeries = branches.length > 0;
  if (data.length === 0 && !branches.some((branch) => (branch.points?.length ?? 0) > 1)) {
    return <div className="ws-chart" />;
  }

  const firstPoint = data[0];
  const lastPoint = data[data.length - 1];
  const historySpan =
    firstPoint && lastPoint
      ? Math.max(lastPoint.timestamp - firstPoint.timestamp, 24 * 60 * 60 * 1000)
      : 0;
  const anchoredPad = multiSeries && lastPoint ? historySpan * SCENARIO_REGION_SHARE : 0;
  const resolvedBranches = branches
    .map((branch) => {
      if (branch.points?.length) return { ...branch, resolved: branch.points };
      if (!lastPoint || branch.start == null || branch.end == null) return null;
      return {
        ...branch,
        resolved: [
          { timestamp: lastPoint.timestamp, value: branch.start },
          { timestamp: lastPoint.timestamp + anchoredPad, value: branch.end },
        ],
      };
    })
    .filter((branch): branch is ProbabilityBranch & { resolved: ChartPoint[] } => branch !== null);

  const allTimestamps = [
    ...data.map((point) => point.timestamp),
    ...resolvedBranches.flatMap((branch) => branch.resolved.map((point) => point.timestamp)),
  ];
  const firstTimestamp = Math.min(...allTimestamps);
  const lastTimestamp = lastPoint?.timestamp ?? Math.max(...allTimestamps);
  const legacyPad = !multiSeries && scenarioBranch ? historySpan * 0.22 : 0;
  const xDomain: [number, number] = multiSeries
    ? [firstTimestamp, Math.max(...allTimestamps)]
    : [firstTimestamp, lastTimestamp + legacyPad];

  const values = [
    ...data.map((point) => point.value),
    ...overlay.map((point) => point.value),
    ...(comparison ? [comparison.value] : []),
    ...(scenarioBranch && !multiSeries ? [scenarioBranch.comparisonBaseline, scenarioBranch.scenarioOdds] : []),
    ...resolvedBranches.flatMap((branch) => branch.resolved.map((point) => point.value)),
  ];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const valueRange = Math.max(max - min, 1);
  const axis = percentAxis ? percentDomain(values) : null;
  const yDomain: [number, number] = axis?.domain ?? [min - valueRange * 0.24, max + valueRange * 0.1];

  const rows = new Map<number, Record<string, number | undefined>>();
  const row = (timestamp: number) => {
    let entry = rows.get(timestamp);
    if (!entry) {
      entry = { timestamp };
      rows.set(timestamp, entry);
    }
    return entry;
  };
  data.forEach((point) => { row(point.timestamp).value = point.value; });
  if (!multiSeries && scenarioBranch && lastPoint) {
    const branchX = lastTimestamp + legacyPad * 0.72;
    const epsilon = Math.max(historySpan * 0.002, 60_000);
    row(branchX).scenarioValue = scenarioBranch.comparisonBaseline;
    row(branchX + epsilon).scenarioValue = scenarioBranch.scenarioOdds;
  } else if (!multiSeries) {
    overlay.forEach((point) => { row(point.timestamp).scenarioValue = point.value; });
  }
  resolvedBranches.forEach((branch, index) => {
    branch.resolved.forEach((point) => { row(point.timestamp)[`branch${index}`] = point.value; });
  });
  const chartData = [...rows.values()].sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));

  const scenarioStroke = (scenarioBranch?.tone ?? overlayTone) === "negative" ? "#c44745" : "#188453";
  const showScenarioLine = !multiSeries && (Boolean(scenarioBranch) || overlay.length > 1);
  const historyStroke = historyColor ?? "var(--market-chart-accent, #299f96)";
  const rightMargin = (percentAxis ? 4 : 2) + (multiSeries ? 10 : scenarioBranch ? 10 : 0);

  function timestampFromPointer(clientX: number) {
    const element = plotRef.current ?? wrapperRef.current;
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    const left = rect.left + PLOT_MARGIN.left;
    const width = rect.width - PLOT_MARGIN.left - rightMargin - (percentAxis ? PERCENT_AXIS_WIDTH : 0);
    const ratio = Math.max(0, Math.min(1, (clientX - left) / Math.max(width, 1)));
    return xDomain[0] + (xDomain[1] - xDomain[0]) * ratio;
  }

  function getIndexFromPointer(clientX: number) {
    const timestamp = timestampFromPointer(clientX);
    return timestamp == null ? -1 : nearestPointIndex(data, Math.min(timestamp, lastTimestamp));
  }

  function emitSelection(startIndex: number, endIndex: number) {
    const start = data[Math.min(startIndex, endIndex)];
    const end = data[Math.max(startIndex, endIndex)];
    if (!start || !end) return;
    const pointChange = end.value - start.value;
    const percentChange = start.value === 0 ? 0 : (pointChange / start.value) * 100;
    onSelectionChange?.({ start, end, pointChange, percentChange });
  }

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (!interactive) return;
    const index = getIndexFromPointer(event.clientX);
    if (index < 0) return;
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    setSelection({ startIndex: index, endIndex: index });
    emitSelection(index, index);
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!interactive) return;
    const hover = getIndexFromPointer(event.clientX);
    if (hover >= 0 && !draggingRef.current) setHoverIndex(hover);
    if (!draggingRef.current) return;
    const index = getIndexFromPointer(event.clientX);
    if (index < 0) return;
    setSelection((previous) => {
      if (!previous) return { startIndex: index, endIndex: index };
      emitSelection(previous.startIndex, index);
      return { startIndex: previous.startIndex, endIndex: index };
    });
  }

  function handlePointerUp(event: React.PointerEvent<HTMLDivElement>) {
    if (!interactive) return;
    draggingRef.current = false;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // no-op
    }
  }

  function clearSelection() {
    setSelection(null);
    onSelectionChange?.(null);
  }

  const lowIndex = selection ? Math.min(selection.startIndex, selection.endIndex) : null;
  const highIndex = selection ? Math.max(selection.startIndex, selection.endIndex) : null;
  const startPoint = lowIndex !== null ? data[lowIndex] : null;
  const endPoint = highIndex !== null ? data[highIndex] : null;

  const legendItems = multiSeries
    ? [
        ...(lastPoint ? [{ id: "__history", label: historyLabel, color: historyStroke, value: lastPoint.value, dashed: false, note: undefined as string | undefined }] : []),
        ...resolvedBranches.map((branch) => ({
          id: branch.id,
          label: branch.label,
          color: branch.color,
          value: branch.resolved[branch.resolved.length - 1]!.value,
          dashed: Boolean(branch.dashed),
          note: branch.note,
        })),
      ]
    : [];

  const readout =
    multiSeries && hoverTimestamp != null
      ? [
          ...(lastPoint && hoverTimestamp <= lastTimestamp
            ? [{ id: "__history", label: historyLabel, color: historyStroke, value: stepValueAt(data, hoverTimestamp) }]
            : []),
          ...resolvedBranches.map((branch) => ({
            id: branch.id,
            label: branch.label,
            color: branch.color,
            value: linearValueAt(branch.resolved, hoverTimestamp),
          })),
        ].filter((item): item is { id: string; label: string; color: string; value: number } => item.value != null)
      : [];
  const readoutTitle =
    hoverTimestamp == null
      ? ""
      : lastPoint && hoverTimestamp <= lastTimestamp
        ? new Date(hoverTimestamp).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
        : scenarioRegionLabel ?? "Scenario";

  const tickLabels = xTicks ? new Map(xTicks.map((tick) => [tick.value, tick.label])) : null;
  const dimmed = (id: string) => highlightedBranchId != null && highlightedBranchId !== id;

  const plot = (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart
        data={chartData}
        margin={{ top: PLOT_MARGIN.top, right: rightMargin, bottom: showTimeAxis ? 22 : PLOT_MARGIN.bottom, left: PLOT_MARGIN.left }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--market-chart-accent, #299f96)" stopOpacity={0.42} />
            <stop offset="55%" stopColor="var(--market-chart-accent, #299f96)" stopOpacity={0.14} />
            <stop offset="100%" stopColor="var(--market-chart-accent, #299f96)" stopOpacity={0} />
          </linearGradient>
        </defs>

        {percentAxis ? (
          <CartesianGrid vertical={false} stroke="var(--market-grid, rgba(128,128,128,.22))" strokeDasharray="2 4" />
        ) : null}

        <XAxis
          dataKey="timestamp"
          type="number"
          domain={xDomain}
          hide={!showTimeAxis}
          ticks={xTicks?.map((tick) => tick.value)}
          tickCount={xTicks ? undefined : 4}
          tick={{ fontSize: 11, fill: "var(--market-text, #686664)" }}
          tickFormatter={(value: number) => {
            if (tickLabels) return tickLabels.get(value) ?? "";
            if (multiSeries && value > lastTimestamp) return "";
            return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
          }}
          axisLine={false}
          tickLine={false}
        />

        <YAxis
          hide={!percentAxis}
          orientation="right"
          width={PERCENT_AXIS_WIDTH}
          domain={yDomain}
          ticks={axis?.ticks}
          tickFormatter={(value: number) => `${value}%`}
          tick={{ fontSize: 11, fill: "var(--market-text, #686664)" }}
          axisLine={false}
          tickLine={false}
        />

        {data.length ? (
          <Area
            type={data.length === 1 ? "linear" : "stepAfter"}
            dataKey="value"
            stroke={historyStroke}
            strokeWidth={multiSeries ? 2.2 : 1.7}
            strokeOpacity={dimmed("__history") ? 0.3 : 1}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill={lineOnly ? "none" : `url(#${gradientId})`}
            fillOpacity={1}
            dot={data.length === 1}
            activeDot={false}
            connectNulls
            isAnimationActive={false}
          />
        ) : null}

        {showScenarioLine ? (
          <Line
            type="linear"
            dataKey="scenarioValue"
            stroke={scenarioStroke}
            strokeDasharray="5 4"
            strokeWidth={scenarioBranch ? 2 : 2.2}
            dot={{ r: scenarioBranch ? 5 : 4 }}
            connectNulls={false}
            activeDot={false}
            isAnimationActive={false}
          />
        ) : null}

        {resolvedBranches.map((branch, index) => (
          <Line
            key={branch.id}
            type="linear"
            dataKey={`branch${index}`}
            name={branch.label}
            stroke={branch.color}
            strokeWidth={highlightedBranchId === branch.id ? 3.6 : 2.6}
            strokeOpacity={dimmed(branch.id) ? 0.25 : 1}
            strokeDasharray={branch.dashed ? "6 5" : undefined}
            dot={false}
            activeDot={false}
            connectNulls
            isAnimationActive={false}
            onClick={onBranchSelect ? () => onBranchSelect(branch.id) : undefined}
            style={onBranchSelect ? { cursor: "pointer" } : undefined}
          />
        ))}

        {resolvedBranches.map((branch) => {
          const end = branch.resolved[branch.resolved.length - 1]!;
          return (
            <ReferenceDot
              key={`${branch.id}-end`}
              x={end.timestamp}
              y={end.value}
              r={highlightedBranchId === branch.id ? 6 : 4.5}
              fill={branch.color}
              fillOpacity={dimmed(branch.id) ? 0.3 : 1}
              stroke="var(--market-chart-dot-stroke, #f8f8f5)"
              strokeWidth={2}
            />
          );
        })}

        {multiSeries && lastPoint ? (
          <ReferenceLine
            x={lastTimestamp}
            stroke="var(--market-text, #20211f)"
            strokeOpacity={0.35}
            strokeDasharray="3 4"
            label={{ value: "Now", position: "insideTopLeft", fontSize: 11, fill: "var(--market-text, #686664)" }}
          />
        ) : null}

        {multiSeries && lastPoint && resolvedBranches.some((branch) => !branch.points?.length) ? (
          <ReferenceDot
            x={lastTimestamp}
            y={resolvedBranches.find((branch) => !branch.points?.length)!.resolved[0]!.value}
            r={4.5}
            fill="var(--market-text, #20211f)"
            stroke="var(--market-chart-dot-stroke, #f8f8f5)"
            strokeWidth={2}
          />
        ) : null}

        {multiSeries && hoverTimestamp != null ? (
          <ReferenceLine x={hoverTimestamp} stroke="var(--market-text, #20211f)" strokeOpacity={0.4} />
        ) : null}

        {!multiSeries && scenarioBranch ? (
          <ReferenceLine x={lastTimestamp} stroke="var(--market-text, #20211f)" strokeOpacity={0.28} strokeDasharray="3 4" />
        ) : null}

        {interactive && !multiSeries ? (
          <Tooltip
            cursor={{ stroke: "var(--market-chart-accent, #299f96)", strokeWidth: 1 }}
            formatter={(value) => [`${Number(value).toFixed(2)}%`, "Published odds"]}
            labelFormatter={(value) =>
              new Date(Number(value)).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric" })
            }
          />
        ) : null}

        {markers.map((marker) => (
          <ReferenceLine
            key={`${marker.timestamp}-${marker.label}`}
            x={marker.timestamp}
            stroke="var(--market-text, #20211f)"
            strokeOpacity={0.16}
            strokeDasharray="3 4"
          />
        ))}

        {comparison ? (
          <ReferenceDot
            x={comparison.timestamp}
            y={comparison.value}
            r={5}
            fill="var(--market-text, #20211f)"
            stroke="var(--market-chart-dot-stroke, #f8f8f5)"
            strokeWidth={2}
          />
        ) : null}

        {data.length === 1 && firstPoint ? (
          <ReferenceDot
            x={firstPoint.timestamp}
            y={firstPoint.value}
            r={6}
            fill={historyStroke}
            stroke="var(--market-chart-dot-stroke, #f8f8f5)"
            strokeWidth={3}
          />
        ) : null}

        {!multiSeries && hoverIndex !== null && data[hoverIndex] && !selection ? (
          <>
            <ReferenceLine x={data[hoverIndex].timestamp} stroke="var(--market-chart-accent, #299f96)" strokeWidth={1.15} />
            <ReferenceDot
              x={data[hoverIndex].timestamp}
              y={data[hoverIndex].value}
              r={6}
              fill="var(--market-chart-accent, #299f96)"
              stroke="var(--market-chart-dot-stroke, #f8f8f5)"
              strokeWidth={3}
            />
          </>
        ) : null}

        {startPoint && endPoint ? (
          <>
            {startPoint.timestamp !== endPoint.timestamp ? (
              <ReferenceArea
                x1={startPoint.timestamp}
                x2={endPoint.timestamp}
                fill="var(--market-chart-accent, #299f96)"
                fillOpacity={0.07}
                strokeOpacity={0}
              />
            ) : null}
            <ReferenceLine x={startPoint.timestamp} stroke="var(--market-chart-accent, #299f96)" strokeWidth={1.15} />
            {startPoint.timestamp !== endPoint.timestamp ? (
              <ReferenceLine x={endPoint.timestamp} stroke="var(--market-chart-accent, #299f96)" strokeWidth={1.15} />
            ) : null}
            <ReferenceDot
              x={startPoint.timestamp}
              y={startPoint.value}
              r={6}
              fill="var(--market-chart-accent, #299f96)"
              stroke="var(--market-chart-dot-stroke, #f8f8f5)"
              strokeWidth={3}
            />
            {startPoint.timestamp !== endPoint.timestamp ? (
              <ReferenceDot
                x={endPoint.timestamp}
                y={endPoint.value}
                r={6}
                fill="var(--market-chart-accent, #299f96)"
                stroke="var(--market-chart-dot-stroke, #f8f8f5)"
                strokeWidth={3}
              />
            ) : null}
          </>
        ) : null}
      </ComposedChart>
    </ResponsiveContainer>
  );

  const interactionLayer =
    interactive && data.length ? (
      <div
        className="ws-chart-interaction-layer"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onDoubleClick={clearSelection}
        aria-label="Drag across the chart to inspect historical odds"
      />
    ) : null;

  if (!multiSeries) {
    return (
      <div ref={wrapperRef} className={`ws-chart trend-${chartTrend(data)}`} data-trend={chartTrend(data)}>
        {plot}
        {interactionLayer}
      </div>
    );
  }

  return (
    <div ref={wrapperRef} className="ws-chart ws-chart-multi" data-series-count={legendItems.length}>
      <ul className="ws-legend" aria-label="Chart series">
        {legendItems.map((item) => {
          const selectable = Boolean(onBranchSelect) && item.id !== "__history";
          const content = (
            <>
              <i className={item.dashed ? "dashed" : ""} style={{ background: item.dashed ? undefined : item.color, borderColor: item.color }} aria-hidden="true" />
              <span className="ws-legend-label">{item.label}</span>
              <strong>{formatPercent(item.value)}</strong>
              {item.note ? <em>{item.note}</em> : null}
            </>
          );
          return (
            <li key={item.id} className={dimmed(item.id) ? "is-dimmed" : highlightedBranchId === item.id ? "is-active" : ""} data-testid={`series-${item.id}`}>
              {selectable ? (
                <button type="button" aria-pressed={highlightedBranchId === item.id} onClick={() => onBranchSelect?.(item.id)}>
                  {content}
                </button>
              ) : (
                <span className="ws-legend-static">{content}</span>
              )}
            </li>
          );
        })}
      </ul>
      <div
        ref={plotRef}
        className="ws-plot"
        onPointerMove={(event) => setHoverTimestamp(timestampFromPointer(event.clientX))}
        onPointerLeave={() => setHoverTimestamp(null)}
      >
        {plot}
        {interactionLayer}
        {readout.length ? (
          <div className="ws-readout" role="status">
            <span>{readoutTitle}</span>
            {readout.map((item) => (
              <div key={item.id}>
                <i style={{ background: item.color }} aria-hidden="true" />
                <span>{item.label}</span>
                <strong>{formatPercent(item.value)}</strong>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
