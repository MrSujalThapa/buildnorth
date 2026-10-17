/** Format a percentage for forecast UI; keep sub-10% values readable. */
export function formatProbabilityPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  const digits = value > 0 && value < 10 ? 1 : 0;
  return `${value.toFixed(digits)}%`;
}
