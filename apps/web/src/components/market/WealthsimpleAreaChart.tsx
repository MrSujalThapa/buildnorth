import {
  useId,
  useRef,
  useState,
} from "react";

import {
  Area,
  AreaChart,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import type {
  ChartMarker,
  ChartPoint,
} from "../../adapters/templateTypes";

import "./wealthsimple-chart.css";
import { chartTrend } from "./chartTrend";

export type ChartSelection = {
  start: ChartPoint;
  end: ChartPoint;

  pointChange: number;
  percentChange: number;
};

type Props = {
  data: ChartPoint[];
  overlay?: ChartPoint[];
  markers?: ChartMarker[];
  comparison?: ChartPoint | null;
  interactive?: boolean;
  onSelectionChange?: (
    selection:
      | ChartSelection
      | null,
  ) => void;
};

function nearestPointIndex(
  data: ChartPoint[],
  targetTimestamp: number,
) {
  if (!data.length) {
    return -1;
  }

  const first = data[0];
  if (!first) {
    return -1;
  }

  let bestIndex = 0;
  let bestDistance = Math.abs(first.timestamp - targetTimestamp);

  for (let index = 1; index < data.length; index += 1) {
    const point = data[index];
    if (!point) continue;
    const distance = Math.abs(point.timestamp - targetTimestamp);

    if (
      distance <
      bestDistance
    ) {
      bestDistance =
        distance;

      bestIndex =
        index;
    }
  }

  return bestIndex;
}

export default function WealthsimpleAreaChart({
  data,
  overlay = [],
  markers = [],
  comparison = null,
  interactive = true,
  onSelectionChange,
}: Props) {
  const rawId =
    useId();

  const gradientId =
    `ws-gradient-${rawId.replace(
      /:/g,
      "",
    )}`;

  const wrapperRef =
    useRef<HTMLDivElement | null>(
      null,
    );

  const draggingRef =
    useRef(false);

  const [
    selection,
    setSelection,
  ] =
    useState<{
      startIndex: number;
      endIndex: number;
    } | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (
    data.length === 0
  ) {
    return (
      <div className="ws-chart" />
    );
  }

  const values =
    [
      ...data.map((point) => point.value),
      ...overlay.map((point) => point.value),
      ...(comparison ? [comparison.value] : []),
    ];

  const min =
    Math.min(...values);

  const max =
    Math.max(...values);

  const valueRange =
    Math.max(
      max - min,
      1,
    );

  const firstPoint = data[0];
  const lastPoint = data[data.length - 1];
  if (!firstPoint || !lastPoint) {
    return <div className="ws-chart" />;
  }

  const firstTimestamp = firstPoint.timestamp;
  const lastTimestamp = lastPoint.timestamp;

  function getIndexFromPointer(
    clientX: number,
  ) {
    const element =
      wrapperRef.current;

    if (!element) {
      return -1;
    }

    const rect =
      element.getBoundingClientRect();

    const rawRatio =
      (clientX -
        rect.left) /
      rect.width;

    const ratio =
      Math.max(
        0,
        Math.min(
          1,
          rawRatio,
        ),
      );

    const timestamp =
      firstTimestamp +
      (lastTimestamp -
        firstTimestamp) *
        ratio;

    return nearestPointIndex(
      data,
      timestamp,
    );
  }

  function emitSelection(
    startIndex: number,
    endIndex: number,
  ) {
    const lowIndex =
      Math.min(
        startIndex,
        endIndex,
      );

    const highIndex =
      Math.max(
        startIndex,
        endIndex,
      );

    const start =
      data[lowIndex];

    const end =
      data[highIndex];

    if (
      !start ||
      !end
    ) {
      return;
    }

    const pointChange =
      end.value -
      start.value;

    const percentChange =
      start.value === 0
        ? 0
        : (pointChange /
            start.value) *
          100;

    onSelectionChange?.({
      start,
      end,
      pointChange,
      percentChange,
    });
  }

  function handlePointerDown(
    event: React.PointerEvent<HTMLDivElement>,
  ) {
    if (!interactive) {
      return;
    }

    const index =
      getIndexFromPointer(
        event.clientX,
      );

    if (index < 0) {
      return;
    }

    draggingRef.current =
      true;

    event.currentTarget.setPointerCapture(
      event.pointerId,
    );

    setSelection({
      startIndex: index,
      endIndex: index,
    });

    emitSelection(
      index,
      index,
    );
  }

  function handlePointerMove(
    event: React.PointerEvent<HTMLDivElement>,
  ) {
    if (!interactive) {
      return;
    }
    const hover = getIndexFromPointer(event.clientX);
    if (hover >= 0 && !draggingRef.current) {
      setHoverIndex(hover);
    }
    if (!draggingRef.current) {
      return;
    }

    const index =
      getIndexFromPointer(
        event.clientX,
      );

    if (index < 0) {
      return;
    }

    setSelection(
      (previous) => {
        if (!previous) {
          return {
            startIndex:
              index,

            endIndex:
              index,
          };
        }

        emitSelection(
          previous.startIndex,
          index,
        );

        return {
          startIndex:
            previous.startIndex,

          endIndex:
            index,
        };
      },
    );
  }

  function handlePointerUp(
    event: React.PointerEvent<HTMLDivElement>,
  ) {
    if (!interactive) {
      return;
    }

    draggingRef.current =
      false;

    try {
      event.currentTarget.releasePointerCapture(
        event.pointerId,
      );
    } catch {
      // no-op
    }
  }

  function clearSelection() {
    setSelection(null);

    onSelectionChange?.(
      null,
    );
  }

  const lowIndex =
    selection
      ? Math.min(
          selection.startIndex,
          selection.endIndex,
        )
      : null;

  const highIndex =
    selection
      ? Math.max(
          selection.startIndex,
          selection.endIndex,
        )
      : null;

  const startPoint =
    lowIndex !== null
      ? data[lowIndex]
      : null;

  const endPoint =
    highIndex !== null
      ? data[highIndex]
      : null;

  return (
    <div
      ref={wrapperRef}
      className={`ws-chart trend-${chartTrend(data)}`}
      data-trend={chartTrend(data)}
    >
      <ResponsiveContainer
        width="100%"
        height="100%"
      >
        <AreaChart
          data={data}
          margin={{
            top: 10,
            right: 2,
            bottom: 0,
            left: 2,
          }}
        >
          <defs>
            <linearGradient
              id={gradientId}
              x1="0"
              y1="0"
              x2="0"
              y2="1"
            >
              <stop
                offset="0%"
                stopColor="var(--market-chart-accent, #299f96)"
                stopOpacity={0.42}
              />

              <stop
                offset="55%"
                stopColor="var(--market-chart-accent, #299f96)"
                stopOpacity={0.14}
              />

              <stop
                offset="100%"
                stopColor="var(--market-chart-accent, #299f96)"
                stopOpacity={0}
              />
            </linearGradient>
          </defs>

          <XAxis
            dataKey="timestamp"
            type="number"
            domain={[
              "dataMin",
              "dataMax",
            ]}
            hide
          />

          <YAxis
            hide
            domain={[
              min -
                valueRange *
                  0.24,

              max +
                valueRange *
                  0.1,
            ]}
          />

          <Area
            type={data.length === 1 ? "linear" : "stepAfter"}
            dataKey="value"
            stroke="var(--market-chart-accent, #299f96)"
            strokeWidth={1.7}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill={`url(#${gradientId})`}
            fillOpacity={1}
            dot={data.length === 1}
            activeDot={false}
            isAnimationActive={
              false
            }
          />

          {overlay.length > 1 ? (
            <Area
              data={overlay}
              type="monotone"
              dataKey="value"
              stroke="var(--market-chart-accent, #299f96)"
              strokeDasharray="5 4"
              strokeWidth={1.4}
              fill="none"
              dot={false}
              activeDot={false}
              isAnimationActive={false}
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

          {data.length === 1 ? (
            <ReferenceDot
              x={firstPoint.timestamp}
              y={firstPoint.value}
              r={6}
              fill="var(--market-chart-accent, #299f96)"
              stroke="var(--market-chart-dot-stroke, #f8f8f5)"
              strokeWidth={3}
            />
          ) : null}

          {hoverIndex !== null && data[hoverIndex] && !selection ? (
            <>
              <ReferenceLine
                x={data[hoverIndex].timestamp}
                stroke="var(--market-chart-accent, #299f96)"
                strokeWidth={1.15}
              />
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

          {startPoint &&
            endPoint && (
              <>
                {startPoint.timestamp !==
                  endPoint.timestamp && (
                  <ReferenceArea
                    x1={
                      startPoint.timestamp
                    }
                    x2={
                      endPoint.timestamp
                    }
                    fill="var(--market-chart-accent, #299f96)"
                    fillOpacity={
                      0.07
                    }
                    strokeOpacity={
                      0
                    }
                  />
                )}

                <ReferenceLine
                  x={
                    startPoint.timestamp
                  }
                  stroke="var(--market-chart-accent, #299f96)"
                  strokeWidth={
                    1.15
                  }
                />

                {startPoint.timestamp !==
                  endPoint.timestamp && (
                  <ReferenceLine
                    x={
                      endPoint.timestamp
                    }
                    stroke="var(--market-chart-accent, #299f96)"
                    strokeWidth={
                      1.15
                    }
                  />
                )}

                <ReferenceDot
                  x={
                    startPoint.timestamp
                  }
                  y={
                    startPoint.value
                  }
                  r={6}
                  fill="var(--market-chart-accent, #299f96)"
                  stroke="var(--market-chart-dot-stroke, #f8f8f5)"
                  strokeWidth={3}
                />

                {startPoint.timestamp !==
                  endPoint.timestamp && (
                  <ReferenceDot
                    x={
                      endPoint.timestamp
                    }
                    y={
                      endPoint.value
                    }
                    r={6}
                    fill="var(--market-chart-accent, #299f96)"
                    stroke="var(--market-chart-dot-stroke, #f8f8f5)"
                    strokeWidth={
                      3
                    }
                  />
                )}
              </>
            )}
        </AreaChart>
      </ResponsiveContainer>

      {interactive && (
        <div
          className="ws-chart-interaction-layer"
          onPointerDown={
            handlePointerDown
          }
          onPointerMove={
            handlePointerMove
          }
          onPointerUp={
            handlePointerUp
          }
          onPointerCancel={
            handlePointerUp
          }
          onDoubleClick={
            clearSelection
          }
          aria-label="Drag across the chart to inspect historical odds"
        />
      )}
    </div>
  );
}
