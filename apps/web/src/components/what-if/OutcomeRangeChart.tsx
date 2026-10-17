import {
  useId,
  useMemo,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type { OutcomePoint } from "../../adapters/templateTypes";

type Props = {
  data: OutcomePoint[];
  currentOdds: number;
};

type SvgPoint = {
  x: number;
  y: number;
};

const WIDTH = 1000;
const HEIGHT = 330;
const PAD_X = 26;
const PAD_Y = 26;

function smoothLine(points: SvgPoint[], tension = 0.88) {
  if (!points.length) {
    return "";
  }

  if (points.length === 1) {
    const only = points[0];
    if (!only) return "";
    return `M ${only.x} ${only.y}`;
  }

  const head = points[0];
  if (!head) return "";
  let path = `M ${head.x.toFixed(2)} ${head.y.toFixed(2)}`;

  for (let index = 0; index < points.length - 1; index += 1) {
    const p1 = points[index];
    const p2 = points[index + 1];
    if (!p1 || !p2) continue;
    const p0 = points[index - 1] ?? p1;
    const p3 = points[index + 2] ?? p2;

    const cp1x = p1.x + ((p2.x - p0.x) / 6) * tension;
    const cp1y = p1.y + ((p2.y - p0.y) / 6) * tension;
    const cp2x = p2.x - ((p3.x - p1.x) / 6) * tension;
    const cp2y = p2.y - ((p3.y - p1.y) / 6) * tension;

    path += ` C ${cp1x.toFixed(2)} ${cp1y.toFixed(2)} ${cp2x.toFixed(2)} ${cp2y.toFixed(2)} ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
  }

  return path;
}

function bandPath(upper: SvgPoint[], lower: SvgPoint[]) {
  if (!upper.length || !lower.length) {
    return "";
  }

  const top = upper
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");

  const bottom = [...lower]
    .reverse()
    .map((point) => `L ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");

  return `${top} ${bottom} Z`;
}

export default function OutcomeRangeChart({ data, currentOdds }: Props) {
  const gradientId = `outcome-band-${useId().replace(/:/g, "")}`;
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  const chart = useMemo(() => {
    if (!data.length) {
      return null;
    }

    const min = Math.max(0, Math.min(...data.map((point) => point.low)) - 2.5);
    const max = Math.min(100, Math.max(...data.map((point) => point.high)) + 2.5);
    const span = Math.max(max - min, 1);

    const xFor = (index: number) =>
      PAD_X + (index / Math.max(data.length - 1, 1)) * (WIDTH - PAD_X * 2);
    const yFor = (value: number) =>
      PAD_Y + ((max - value) / span) * (HEIGHT - PAD_Y * 2);

    const likely = data.map((point, index) => ({ x: xFor(index), y: yFor(point.likely) }));
    const upper = data.map((point, index) => ({ x: xFor(index), y: yFor(point.high) }));
    const lower = data.map((point, index) => ({ x: xFor(index), y: yFor(point.low) }));

    return {
      likely,
      upper,
      lower,
      likelyPath: smoothLine(likely),
      bandPath: bandPath(upper, lower),
      baselineY: yFor(currentOdds),
    };
  }, [data, currentOdds]);

  if (!chart) {
    return (
      <div className="outcome-chart-empty">
        We need a priced baseline before we can show a possible outcome range.
      </div>
    );
  }

  const active = activeIndex === null ? null : data[activeIndex];
  const activeSvg = activeIndex === null ? null : chart.likely[activeIndex];

  function updateActive(event: ReactPointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const index = Math.round(ratio * (data.length - 1));
    setActiveIndex(index);
  }

  return (
    <div className="outcome-chart-wrap">
      <div className="outcome-chart-readout">
        {active ? (
          <>
            <span>Week {Math.max(1, Math.round(((active.step + 1) / data.length) * 12))}</span>
            <strong>{active.likely.toFixed(1)}% likely</strong>
            <span>{active.low.toFixed(1)}ΓÇô{active.high.toFixed(1)}% range</span>
          </>
        ) : (
          <>
            <span>Possible outcomes</span>
            <strong>{data[data.length - 1]?.likely.toFixed(1) ?? "—"}% most likely</strong>
            <span>Move across the chart to explore</span>
          </>
        )}
      </div>

      <svg
        className="outcome-chart-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="Possible outcome range over time"
        onPointerMove={updateActive}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          updateActive(event);
        }}
        onPointerLeave={() => setActiveIndex(null)}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--what-if-accent)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--what-if-accent)" stopOpacity="0.03" />
          </linearGradient>
        </defs>

        <line
          x1={PAD_X}
          x2={WIDTH - PAD_X}
          y1={chart.baselineY}
          y2={chart.baselineY}
          className="outcome-current-line"
        />

        <path d={chart.bandPath} fill={`url(#${gradientId})`} className="outcome-band" />

        <path
          d={chart.likelyPath}
          fill="none"
          stroke="var(--what-if-accent)"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="outcome-likely-line"
        />

        {chart.likely[0] ? (
          <circle
            cx={chart.likely[0].x}
            cy={chart.likely[0].y}
            r="6.5"
            className="outcome-start-dot"
          />
        ) : null}

        {chart.likely[chart.likely.length - 1] ? (
          <circle
            cx={chart.likely[chart.likely.length - 1]!.x}
            cy={chart.likely[chart.likely.length - 1]!.y}
            r="6.5"
            className="outcome-end-dot"
          />
        ) : null}

        {active && activeSvg ? (
          <>
            <line
              x1={activeSvg.x}
              x2={activeSvg.x}
              y1={PAD_Y}
              y2={HEIGHT - PAD_Y}
              className="outcome-scrub-line"
            />
            <circle
              cx={activeSvg.x}
              cy={activeSvg.y}
              r="8"
              className="outcome-active-dot"
            />
          </>
        ) : null}
      </svg>
    </div>
  );
}
