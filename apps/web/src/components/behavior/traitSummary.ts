import type { BehaviorDimension } from "./ExecutionProfileRadar";

export const TRAIT_COLORS: Record<string, string> = {
  weekly_applications: "#2ec4b6",
  weekly_focus_hours: "#ff9f1c",
  weekly_study_hours: "#ff9f1c",
  monthly_savings: "#2e86de",
  weekly_running_km: "#6a994e",
  reading_minutes: "#b08968",
  books_per_month: "#b08968",
  sleep_hours: "#c9184a",
};

const FALLBACK = ["#2ec4b6", "#ff9f1c", "#2e86de", "#e71d36", "#6a994e", "#c9184a"];

export function traitColor(key: string, index: number): string {
  return TRAIT_COLORS[key] ?? FALLBACK[index % FALLBACK.length] ?? "#1f8a70";
}

export function chartLabel(label: string): string {
  return label;
}

/** Consumer copy from the parameter's measured average, not a personality trait. */
export function traitSummary(item: BehaviorDimension): string {
  if (item.limited_evidence || item.value == null || item.display_percent == null) {
    return item.provenance.details[0] ?? "Not enough measurements yet.";
  }
  const measured = item.provenance.details.find((line) => line.startsWith("Current average"));
  if (measured) return measured;
  const count = item.provenance.comparable_commitments;
  return count
    ? `Based on ${count} observation${count === 1 ? "" : "s"} in the selected window.`
    : "Measured from recorded observations.";
}
