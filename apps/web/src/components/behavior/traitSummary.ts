import type { BehaviorDimension } from "./ExecutionProfileRadar";

export const TRAIT_COLORS: Record<string, string> = {
  follow_through: "#2ec4b6",
  consistency: "#ff9f1c",
  commitment_realism: "#e71d36",
  momentum: "#2e86de",
  reliability: "#6a994e",
  recovery: "#c9184a",
  evidence_quality: "#7a746c",
  goal_relevance: "#b08968",
};

const FALLBACK = ["#2ec4b6", "#ff9f1c", "#2e86de", "#e71d36", "#6a994e", "#c9184a"];

export function traitColor(key: string, index: number): string {
  return TRAIT_COLORS[key] ?? FALLBACK[index % FALLBACK.length] ?? "#1f8a70";
}

export function chartLabel(label: string): string {
  if (label === "Commitment realism") return "Planning";
  if (label === "Recovery after misses") return "Recovery";
  return label;
}

/** Consumer copy. Only states what the measured counts and score support. */
export function traitSummary(item: BehaviorDimension): string {
  if (item.limited_evidence || item.value == null || item.display_percent == null) {
    return "Not enough history yet.";
  }
  const count = item.provenance.comparable_commitments;
  const completed = Math.round(item.provenance.completed);
  const percent = item.display_percent;

  if (item.key === "follow_through" && count > 0) {
    return `You completed ${completed} of ${count} comparable commitments.`;
  }
  if (item.key === "consistency") {
    return percent >= 60
      ? "Your routine has been more consistent recently."
      : "Your routine has varied more than a steady cadence.";
  }
  if (item.key === "commitment_realism") {
    return percent >= 70
      ? "What you plan and what you finish have been close."
      : "Finished work has often landed short of the plan.";
  }
  if (item.key === "momentum") {
    return percent >= 55
      ? "Recent follow-through is ahead of your longer record."
      : "Recent follow-through is behind your longer record.";
  }
  if (item.key === "reliability") {
    return "This is the cautious floor of your follow-through, not a best case.";
  }
  if (item.key === "recovery" && count > 0) {
    return percent >= 60
      ? "You usually resume within a week after a miss."
      : "Getting back within a week after a miss has been uncommon.";
  }
  return "Measured from your recorded commitments.";
}
