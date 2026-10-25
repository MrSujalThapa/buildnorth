"""MCP Apps Odds Explorer: static HTML resource plus extension advertisement.

The HTML is a template. It never embeds tokens, goal IDs in URLs that a host
could fetch unauthenticated, or private probability data. Chart data arrives
from the host as `ui/notifications/tool-result` after `ui/initialize`.
"""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID, Apps, ResourceCsp

ODDS_UI_LEGACY_URI = "ui://playitout/odds-explorer"
ODDS_UI_URI = "ui://playitout/odds-explorer/v2"
WHATIF_UI_URI = "ui://playitout/what-if/v1"
ODDS_UI_MIME = APP_MIME_TYPE
UI_EXTENSION_ID = EXTENSION_ID

ODDS_EXPLORER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PlayItOut Odds Explorer</title>
  <style>
    :root {
      --bg: #f8f8f5;
      --ink: #20211f;
      --muted: #777b78;
      --border: #e3e4df;
      --accent: #299f96;
      --neg: #c85f3e;
    }
    html, body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    }
    .wrap { padding: 16px 16px 20px; }
    .price { font-size: 40px; font-weight: 700; letter-spacing: -0.04em; line-height: 1; }
    .hint { margin-top: 8px; color: var(--muted); font-size: 14px; }
    svg { display: block; width: 100%; height: 220px; touch-action: none; }
    .ranges {
      margin-top: 10px; padding: 4px; display: grid; grid-template-columns: repeat(5, 1fr);
      gap: 4px; border: 1px solid var(--border); border-radius: 999px;
    }
    .ranges button {
      height: 40px; border: 0; border-radius: 999px; background: transparent;
      color: var(--ink); font-weight: 650; cursor: pointer;
    }
    .ranges button[aria-pressed="true"] { background: var(--accent); color: #fff; }
    .help { margin-top: 10px; color: var(--muted); font-size: 13px; }
    .marker { cursor: pointer; }
  </style>
</head>
<body>
  <div class="wrap">
    <div id="quote">
      <div class="price" id="price">—</div>
      <div class="hint" id="hint">Waiting for authorized forecast history.</div>
    </div>
    <svg id="chart" viewBox="0 0 640 220" role="img" aria-label="Historical odds">
      <defs>
        <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#299f96" stop-opacity="0.42" />
          <stop offset="100%" stop-color="#299f96" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path id="area" fill="url(#fill)" />
      <path id="line" fill="none" stroke="#299f96" stroke-width="2" stroke-linecap="round" />
      <g id="markers"></g>
      <g id="overlay"></g>
      <line id="cross" x1="0" x2="0" y1="8" y2="212" stroke="#299f96" stroke-width="1.15" />
      <circle id="dot" r="6" fill="#299f96" stroke="#f8f8f5" stroke-width="3" />
    </svg>
    <div class="ranges" role="group" aria-label="Chart range">
      <button type="button" data-range="1D">1D</button>
      <button type="button" data-range="1W">1W</button>
      <button type="button" data-range="1M">1M</button>
      <button type="button" data-range="1Y">1Y</button>
      <button type="button" data-range="ALL" aria-pressed="true">ALL</button>
    </div>
    <div class="help" id="inspect">Drag or slide to inspect published odds. Evidence ticks are inspectable. This view cannot change your forecast.</div>
  </div>
  <script>
    const RANGE_MS = { "1D": 86400000, "1W": 604800000, "1M": 2592000000, "1Y": 31536000000, ALL: null };
    let series = [];
    let markers = [];
    let overlay = [];
    let range = "ALL";
    let hostReady = false;

    function post(message) {
      try { window.parent.postMessage(message, "*"); } catch (error) {}
    }
    function sendRequest(method, params) {
      const id = Math.random().toString(36).slice(2);
      post({ jsonrpc: "2.0", id, method, params });
    }
    function sendNotification(method, params) {
      post({ jsonrpc: "2.0", method, params: params || {} });
    }
    function sendInitialized() {
      if (hostReady) return;
      hostReady = true;
      sendNotification("ui/notifications/initialized", {});
      sendNotification("ui/notifications/size-changed", {
        width: Number(document.documentElement.scrollWidth) || 640,
        height: Number(document.documentElement.scrollHeight) || 360
      });
    }

    function applyHostStyles(hostContext) {
      const vars = hostContext && hostContext.styles && hostContext.styles.variables;
      if (!vars) return;
      const root = document.documentElement;
      if (vars["--color-background-primary"]) root.style.setProperty("--bg", vars["--color-background-primary"]);
      if (vars["--color-text-primary"]) root.style.setProperty("--ink", vars["--color-text-primary"]);
    }

    function unwrap(payload) {
      if (!payload) return null;
      if (payload.structuredContent || payload.structured_content) return payload.structuredContent || payload.structured_content;
      if (payload.result) return unwrap(payload.result);
      if (payload.toolResult) return unwrap(payload.toolResult);
      if (payload.toolOutput) return unwrap(payload.toolOutput);
      if (Array.isArray(payload.points) || payload.status) return payload;
      return null;
    }

    function ingest(payload) {
      const data = unwrap(payload);
      if (!data) return;
      series = Array.isArray(data.points) ? data.points : [];
      markers = Array.isArray(data.evidence_markers) ? data.evidence_markers : [];
      overlay = Array.isArray(data.overlay) ? data.overlay : [];
      draw();
    }

    function visiblePoints() {
      if (!series.length || range === "ALL") return series.slice();
      const latest = series[series.length - 1].timestamp_ms;
      const cutoff = latest - RANGE_MS[range];
      const filtered = series.filter((p) => p.timestamp_ms >= cutoff);
      return filtered.length ? filtered : [series[series.length - 1]];
    }

    function xOf(points, ts, width) {
      const t0 = points[0].timestamp_ms;
      const t1 = points[points.length - 1].timestamp_ms;
      if (t1 === t0) return width / 2;
      return 8 + (width - 16) * (ts - t0) / (t1 - t0);
    }
    function yOf(points, value, height) {
      const values = points.map((p) => p.probability_pct);
      const lo = Math.min.apply(null, values);
      const hi = Math.max.apply(null, values);
      const span = Math.max(hi - lo, 1);
      return height - 12 - (height - 28) * (value - lo) / span;
    }

    function markerNear(points, shown) {
      if (!markers.length || !shown) return null;
      let best = null, dist = Infinity;
      for (const mark of markers) {
        const d = Math.abs(mark.timestamp_ms - shown.timestamp_ms);
        if (d < dist) { best = mark; dist = d; }
      }
      const span = Math.max(points[points.length - 1].timestamp_ms - points[0].timestamp_ms, 1);
      return dist / span < 0.04 ? best : null;
    }

    function draw(active) {
      const width = 640, height = 220;
      const points = visiblePoints();
      const price = document.getElementById("price");
      const hint = document.getElementById("hint");
      const inspect = document.getElementById("inspect");
      const area = document.getElementById("area");
      const line = document.getElementById("line");
      document.getElementById("markers").innerHTML = "";
      document.getElementById("overlay").innerHTML = "";
      if (!points.length) {
        price.textContent = "Not priced";
        hint.textContent = "No published forecast receipts yet.";
        inspect.textContent = "PlayItOut will not invent a series for an unpublished goal.";
        area.setAttribute("d", "");
        line.setAttribute("d", "");
        return;
      }
      const shown = active || points[points.length - 1];
      price.textContent = Number(shown.probability_pct).toFixed(1) + "%";
      hint.textContent = new Date(shown.timestamp_ms).toLocaleString("en-CA", {
        month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit"
      });
      const nearby = markerNear(points, shown);
      inspect.textContent = nearby && nearby.label
        ? ("Evidence: " + nearby.label)
        : "Drag or slide to inspect published odds. Evidence ticks are inspectable. This view cannot change your forecast.";
      const coords = points.map((p) => [xOf(points, p.timestamp_ms, width), yOf(points, p.probability_pct, height)]);
      if (coords.length === 1) {
        const [x, y] = coords[0];
        line.setAttribute("d", "");
        area.setAttribute("d", "");
        document.getElementById("dot").setAttribute("cx", x);
        document.getElementById("dot").setAttribute("cy", y);
        document.getElementById("cross").setAttribute("x1", x);
        document.getElementById("cross").setAttribute("x2", x);
      } else {
        const path = coords.map((c, i) => (i ? "L" : "M") + c[0] + " " + c[1]).join(" ");
        line.setAttribute("d", path);
        const last = coords[coords.length - 1];
        const first = coords[0];
        area.setAttribute("d", path + " L" + last[0] + " " + (height - 8) + " L" + first[0] + " " + (height - 8) + " Z");
        const activeCoord = [xOf(points, shown.timestamp_ms, width), yOf(points, shown.probability_pct, height)];
        document.getElementById("dot").setAttribute("cx", activeCoord[0]);
        document.getElementById("dot").setAttribute("cy", activeCoord[1]);
        document.getElementById("cross").setAttribute("x1", activeCoord[0]);
        document.getElementById("cross").setAttribute("x2", activeCoord[0]);
      }
      markers.forEach((mark) => {
        const x = xOf(points, mark.timestamp_ms, width);
        const tick = document.createElementNS("http://www.w3.org/2000/svg", "line");
        tick.setAttribute("class", "marker");
        tick.setAttribute("x1", x); tick.setAttribute("x2", x);
        tick.setAttribute("y1", 8); tick.setAttribute("y2", 212);
        tick.setAttribute("stroke", nearby === mark ? "#20211f" : "#20211f");
        tick.setAttribute("stroke-opacity", nearby === mark ? "0.45" : "0.18");
        tick.setAttribute("stroke-dasharray", "3 4");
        tick.setAttribute("data-label", mark.label || "");
        document.getElementById("markers").appendChild(tick);
      });
    }

    function nearest(clientX) {
      const svg = document.getElementById("chart");
      const rect = svg.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      const points = visiblePoints();
      if (!points.length) return null;
      const t0 = points[0].timestamp_ms;
      const t1 = points[points.length - 1].timestamp_ms;
      const ts = t0 + (t1 - t0) * ratio;
      let best = points[0], dist = Math.abs(points[0].timestamp_ms - ts);
      for (const p of points) {
        const d = Math.abs(p.timestamp_ms - ts);
        if (d < dist) { best = p; dist = d; }
      }
      return best;
    }

    document.getElementById("chart").addEventListener("pointerdown", (event) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      draw(nearest(event.clientX));
    });
    document.getElementById("chart").addEventListener("pointermove", (event) => {
      draw(nearest(event.clientX));
    });
    document.querySelectorAll("[data-range]").forEach((button) => {
      button.addEventListener("click", () => {
        range = button.getAttribute("data-range");
        document.querySelectorAll("[data-range]").forEach((item) => {
          item.setAttribute("aria-pressed", item === button ? "true" : "false");
        });
        draw();
      });
    });

    window.addEventListener("message", (event) => {
      const data = event.data;
      if (!data || data.jsonrpc !== "2.0") return;
      if (data.id != null && data.result && (data.result.protocolVersion || data.result.hostInfo || data.result.hostContext)) {
        applyHostStyles(data.result.hostContext);
        ingest(data.result.hostContext && data.result.hostContext.toolResult);
        sendInitialized();
      }
      if (data.method === "ui/notifications/tool-result") ingest(data.params);
      if (data.method === "ui/notifications/tool-input") return;
      if (data.method === "ui/notifications/host-context-changed") {
        applyHostStyles(data.params || {});
        ingest(data.params);
      }
    });

    sendRequest("ui/initialize", {
      protocolVersion: "2026-01-26",
      appInfo: { name: "PlayItOut Odds Explorer", version: "0.5.1" },
      appCapabilities: { availableDisplayModes: ["inline"] }
    });
    setTimeout(sendInitialized, 500);
    window.PlayItOutOdds = { ingest, visiblePoints: () => visiblePoints(), range: () => range, sendInitialized };
  </script>
</body>
</html>
"""


def build_odds_apps() -> Apps:
    """Official MCP Apps extension: HTML resource plus MIME type hosts require."""
    apps = Apps()
    csp = ResourceCsp(connect_domains=[], resource_domains=[])
    apps.add_html_resource(
        ODDS_UI_URI,
        ODDS_EXPLORER_HTML,
        name="Odds Explorer",
        title="PlayItOut Odds Explorer",
        description="Interactive historical probability chart. Data comes from show_odds_chart.",
        csp=csp,
    )
    apps.add_html_resource(
        ODDS_UI_LEGACY_URI,
        ODDS_EXPLORER_HTML,
        name="Odds Explorer (legacy URI)",
        title="PlayItOut Odds Explorer",
        description="Same Odds Explorer served at the original ui:// URI for cached hosts.",
        csp=csp,
    )
    whatif_html = Path(__file__).with_name("whatif_app.html").read_text(encoding="utf-8")
    apps.add_html_resource(
        WHATIF_UI_URI,
        whatif_html,
        name="What If",
        title="PlayItOut What If",
        description="Actual PlayItOut What If components with owner-scoped numerical results.",
        csp=csp,
    )
    return apps
