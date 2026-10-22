import type { BehaviorDimension } from "./ExecutionProfileRadar";

export const TRAIT_COLORS: Record<string, string> = {
  follow_through: "#1f8a70",
  consistency: "#c9842a",
  commitment_realism: "#c45c4a",
  momentum: "#3b6fd6",
  reliability: "#2f6b4f",
  recovery: "#b4536a",
  evidence_quality: "#6d645c",
  goal_relevance: "#8a6232",
};

const FALLBACK = ["#1f8a70", "#c9842a", "#3b6fd6", "#c45c4a", "#2f6b4f", "#b4536a"];

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
