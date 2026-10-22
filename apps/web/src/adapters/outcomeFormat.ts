/**
 * Simulated outcomes (`outcome_quantiles`, `distribution_bins`, `fan`) are in the
 * goal's own unit — seconds, USD, books — never probabilities.
 */
export type OutcomeScale = {
  unit: string | null;
  target: number | null;
  direction: "at_least" | "at_most";
};

const SECONDS = new Set(["seconds", "second", "sec", "secs", "s"]);
const DOLLARS = new Set(["usd", "$", "dollars"]);

function clock(totalSeconds: number): string {
  const sign = totalSeconds < 0 ? "-" : "";
  const abs = Math.abs(Math.round(totalSeconds));
  const hours = Math.floor(abs / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const seconds = abs % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours ? `${sign}${hours}:${pad(minutes)}:${pad(seconds)}` : `${sign}${minutes}:${pad(seconds)}`;
}

export function formatOutcome(value: number, unit: string | null): string {
  if (!Number.isFinite(value)) return "—";
  const key = (unit ?? "").trim().toLowerCase();
  if (SECONDS.has(key)) return Math.abs(value) >= 60 ? clock(value) : `${Math.round(value)} s`;
  if (DOLLARS.has(key)) {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
  }
  const number = plainNumber(value);
  return unit ? `${number} ${unit}` : number;
}

function plainNumber(value: number): string {
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return Number(value.toFixed(digits)).toLocaleString("en-US");
}

export function formatOutcomeRange(low: number | null, high: number | null, unit: string | null): string {
  if (low == null || high == null || !Number.isFinite(low) || !Number.isFinite(high)) return "—";
  if (Math.abs(high - low) < 1e-9) return "—";
  const [a, b] = [Math.min(low, high), Math.max(low, high)];
  const key = (unit ?? "").trim().toLowerCase();
  if (SECONDS.has(key) || DOLLARS.has(key)) return `${formatOutcome(a, unit)}–${formatOutcome(b, unit)}`;
  const span = `${plainNumber(a)}–${plainNumber(b)}`;
  return unit ? `${span} ${unit}` : span;
}

export function targetLabel(scale: OutcomeScale): string | null {
  if (scale.target == null) return null;
  return `Target ${scale.direction === "at_most" ? "≤" : "≥"} ${formatOutcome(scale.target, scale.unit)}`;
}
