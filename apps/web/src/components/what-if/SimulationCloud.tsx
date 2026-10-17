import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type {
  AxisSpec,
  CloudLayout,
  RepresentativePoint,
  SimulationCluster,
  SimulationPoint,
} from "../../adapters/simulationTypes";

export type CloudSeries = {
  id: string;
  label: string;
  points: SimulationPoint[];
  tone: "aqua" | "neutral" | "muted" | "negative";
  visible: boolean;
};

type ClusterAnchor = SimulationCluster & { x: number; y: number };

type Props = {
  series: CloudSeries[];
  xAxis: AxisSpec;
  yAxis: AxisSpec;
  layout: CloudLayout;
  selectedId: number | null;
  onSelect: (point: SimulationPoint | null) => void;
  representatives?: RepresentativePoint[];
  clusters?: ClusterAnchor[];
  targetY?: number;
  targetLabel?: string;
  ariaLabel: string;
};

const PAD = { top: 28, right: 18, bottom: 36, left: 46 };

function toneColor(tone: CloudSeries["tone"], ink: string, accent: string, muted: string, negative: string) {
  if (tone === "aqua") {
    return accent;
  }
  if (tone === "negative") {
    return negative;
  }
  if (tone === "muted") {
    return muted;
  }
  return ink;
}

function project(
  value: number,
  min: number,
  max: number,
  start: number,
  end: number,
) {
  const ratio = (value - min) / Math.max(max - min, 1e-6);
  return start + ratio * (end - start);
}

export default function SimulationCloud({
  series,
  xAxis,
  yAxis,
  layout,
  selectedId,
  onSelect,
  representatives = [],
  clusters = [],
  targetY,
  targetLabel,
  ariaLabel,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 640, height: 360 });
  const [announce, setAnnounce] = useState("");

  const visiblePoints = useMemo(
    () =>
      series.flatMap((item) =>
        item.visible
          ? item.points.map((point) => ({ point, seriesId: item.id, tone: item.tone }))
          : [],
      ),
    [series],
  );

  const selected = visiblePoints.find((item) => item.point.id === selectedId)?.point ?? null;

  useEffect(() => {
    const node = wrapRef.current;
    if (!node) {
      return;
    }

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      setSize({
        width: Math.max(280, Math.floor(entry.contentRect.width)),
        height: Math.max(240, Math.floor(entry.contentRect.height)),
      });
    });

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size.width * dpr;
    canvas.height = size.height * dpr;
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const host = wrapRef.current ?? document.documentElement;
    const read = (name: string, fallback: string) =>
      getComputedStyle(host).getPropertyValue(name).trim() || fallback;
    const ink = read("--what-if-ink", "#161513");
    const muted = read("--what-if-muted", "#686664");
    const faint = read("--what-if-faint", "#8a8782");
    const border = read("--what-if-border", "#e4e2e1");
    const accent = read("--what-if-accent", "#1f8f86");
    const negative = read("--what-if-negative", "#b56a52");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    ctx.clearRect(0, 0, size.width, size.height);

    const innerW = size.width - PAD.left - PAD.right;
    const innerH = size.height - PAD.top - PAD.bottom;

    ctx.strokeStyle = border;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD.left, PAD.top);
    ctx.lineTo(PAD.left, PAD.top + innerH);
    ctx.lineTo(PAD.left + innerW, PAD.top + innerH);
    ctx.stroke();

    ctx.fillStyle = faint;
    ctx.font = "11px \"Instrument Sans\", sans-serif";
    ctx.fillText(xAxis.label, PAD.left, size.height - 10);
    ctx.save();
    ctx.translate(12, PAD.top + innerH);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(layout === "beeswarm" ? "Likelihood" : yAxis.label, 0, 0);
    ctx.restore();

    if (targetY !== undefined) {
      const y = project(targetY, yAxis.min, yAxis.max, PAD.top + innerH, PAD.top);
      ctx.strokeStyle = accent;
      ctx.globalAlpha = 0.45;
      ctx.setLineDash([4, 5]);
      ctx.beginPath();
      ctx.moveTo(PAD.left, y);
      ctx.lineTo(PAD.left + innerW, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      ctx.fillStyle = accent;
      ctx.fillText(targetLabel ?? `${Math.round(targetY)}%`, PAD.left + 6, y - 6);
    }

    const dimmed = selectedId !== null;
    const dense = visiblePoints.length > 80;
    const baseR = dense ? 1.55 : 5.2;

    for (const item of visiblePoints) {
      const x = project(item.point.x, xAxis.min, xAxis.max, PAD.left, PAD.left + innerW);
      const y =
        layout === "beeswarm"
          ? project(item.point.y, 0.02, 0.98, PAD.top + innerH, PAD.top)
          : project(item.point.y, yAxis.min, yAxis.max, PAD.top + innerH, PAD.top);
      const isSelected = item.point.id === selectedId;
      const color = toneColor(item.tone, ink, accent, muted, negative);

      ctx.beginPath();
      ctx.fillStyle = color;
      ctx.globalAlpha = dimmed && !isSelected ? 0.16 : item.tone === "aqua" ? (dense ? 0.55 : 0.92) : dense ? 0.38 : 0.78;
      ctx.arc(x, y, isSelected ? Math.max(baseR + 2.5, 6) : baseR, 0, Math.PI * 2);
      ctx.fill();

      if (isSelected) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = accent;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(x, y, reduced ? 7 : 9, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    ctx.globalAlpha = 1;
  }, [layout, selectedId, series, size.height, size.width, targetLabel, targetY, visiblePoints, xAxis, yAxis]);

  function pointFromEvent(event: ReactPointerEvent<HTMLCanvasElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const innerW = size.width - PAD.left - PAD.right;
    const innerH = size.height - PAD.top - PAD.bottom;

    let nearest: (typeof visiblePoints)[number] | null = null;
    let nearestDist = visiblePoints.length > 80 ? 16 : 22;

    for (const item of visiblePoints) {
      const x = project(item.point.x, xAxis.min, xAxis.max, PAD.left, PAD.left + innerW);
      const y =
        layout === "beeswarm"
          ? project(item.point.y, 0.02, 0.98, PAD.top + innerH, PAD.top)
          : project(item.point.y, yAxis.min, yAxis.max, PAD.top + innerH, PAD.top);
      const dist = Math.hypot(px - x, py - y);
      if (dist < nearestDist) {
        nearest = item;
        nearestDist = dist;
      }
    }

    return nearest?.point ?? null;
  }

  function selectPoint(point: SimulationPoint | null) {
    onSelect(point);
    setAnnounce(
      point
        ? `Simulation ${point.id} selected. ${xAxis.format(point.x)}. This is a hypothetical sampled future.`
        : "Selection cleared",
    );
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!representatives.length) {
      return;
    }
    const ids = representatives.map((item) => item.point.id);
    const current = selectedId === null ? -1 : ids.indexOf(selectedId);
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      const next = representatives[(current + 1) % representatives.length];
      if (next) selectPoint(next.point);
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = representatives[(current - 1 + representatives.length) % representatives.length];
      if (next) selectPoint(next.point);
    }
    if (event.key === "Escape") {
      selectPoint(null);
    }
  }

  return (
    <div className="sim-cloud" ref={wrapRef}>
      <div
        className="sim-cloud-stage"
        tabIndex={0}
        role="application"
        aria-label={ariaLabel}
        onKeyDown={onKeyDown}
      >
        <canvas
          ref={canvasRef}
          onPointerDown={(event) => {
            const point = pointFromEvent(event);
            selectPoint(point);
          }}
        />

        {clusters.slice(0, 4).map((cluster) => {
          const innerW = size.width - PAD.left - PAD.right;
          const innerH = size.height - PAD.top - PAD.bottom;
          const left = project(cluster.x, xAxis.min, xAxis.max, PAD.left, PAD.left + innerW);
          const top =
            layout === "beeswarm"
              ? PAD.top + 12
              : project(cluster.y, yAxis.min, yAxis.max, PAD.top + innerH, PAD.top);
          return (
            <span
              key={cluster.id}
              className={`sim-cloud-label ${cluster.tone}`}
              style={{ left, top }}
            >
              {cluster.short}
            </span>
          );
        })}

        {representatives.map((item) => {
          const innerW = size.width - PAD.left - PAD.right;
          const innerH = size.height - PAD.top - PAD.bottom;
          const left = project(item.point.x, xAxis.min, xAxis.max, PAD.left, PAD.left + innerW);
          const top =
            layout === "beeswarm"
              ? project(item.point.y, 0.02, 0.98, PAD.top + innerH, PAD.top)
              : project(item.point.y, yAxis.min, yAxis.max, PAD.top + innerH, PAD.top);
          const active = item.point.id === selectedId;
          return (
            <button
              key={item.kind}
              type="button"
              className={active ? "sim-rep-pin selected" : "sim-rep-pin"}
              style={{ left, top }}
              onClick={() => selectPoint(item.point)}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      <div className="sim-cloud-a11y">
        <p className="visually-hidden" aria-live="polite">{announce}</p>
        {selected ? (
          <p className="visually-hidden">
            Selected simulation {selected.id}. {xAxis.format(selected.x)}. Hypothetical sampled future, not a forecast.
          </p>
        ) : null}
        {representatives.length ? (
          <ul className="sim-rep-list" aria-label="Representative simulations">
            {representatives.map((item) => (
              <li key={item.kind}>
                <button
                  type="button"
                  className={item.point.id === selectedId ? "selected" : ""}
                  onClick={() => selectPoint(item.point)}
                >
                  {item.label}
                  <span>{xAxis.format(item.point.x)}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
