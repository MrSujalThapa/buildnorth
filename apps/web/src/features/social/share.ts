import type { PublicMarketDetail } from "../../api/client";
import {
  categoryLabel,
  criteriaRows,
  formatLongDate,
  formatShortDate,
  marketUpdates,
  milestoneText,
  publicMarketStats,
  signedPoints,
  updateContext,
} from "../../components/social/publicMarketView";

export async function shareLink(input: { url: string; title: string }): Promise<"shared" | "copied"> {
  if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
    try {
      await navigator.share({ title: input.title, text: input.title, url: input.url });
      return "shared";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
    }
  }
  await navigator.clipboard.writeText(input.url);
  return "copied";
}

export function absoluteUrl(path: string): string {
  if (path.startsWith("http")) return path;
  return `${window.location.origin}${path.startsWith("/") ? path : `/${path}`}`;
}

export const ASSISTANT_SUMMARY_UPDATE_LIMIT = 6;

function percent(probability: number): string {
  return `${(probability * 100).toFixed(1)}%`;
}

/**
 * Plain-text market summary for pasting into a general AI assistant. Built only from
 * the public market payload, which the API already limits to owner-published fields.
 */
export function buildAssistantSummary(market: PublicMarketDetail, url: string | null): string {
  const blueprint = market.blueprint;
  const stats = publicMarketStats(market);
  const lines: string[] = [
    "I'm sharing a goal market from Play It Out. Please help me reason about it. The odds are model forecasts published by the creator, not guarantees, and the changes listed for each update are what was recorded at that time, not their causes.",
    "",
    `# ${market.title}`,
    `- Creator: @${market.creator.handle}`,
    market.visibility === "public" && url ? `- Public market: ${url}` : "- Visibility: private, not published",
  ];
  const lastPoint = market.history.at(-1);
  if (stats.latestOdds != null && lastPoint) {
    lines.push(`- Published odds: ${stats.latestOdds.toFixed(1)}% as of ${formatShortDate(lastPoint.created_at)}`);
  } else {
    lines.push(`- Published odds: ${market.forecast.status === "withheld" ? "withheld" : "none yet"}`);
  }
  const deadline = formatLongDate(blueprint.deadline);
  if (deadline) lines.push(`- Deadline: ${deadline}`);
  lines.push(`- Category: ${categoryLabel(blueprint.category || market.category)}`);

  const criteria = criteriaRows(blueprint.success_criteria);
  const description = blueprint.description || market.description;
  if (description || criteria.length) {
    lines.push("", "## What counts as success");
    if (description) lines.push(description);
    for (const row of criteria) lines.push(`- ${row.label}: ${row.value}`);
  }
  if (blueprint.strategies.length) {
    lines.push("", blueprint.strategies_source === "suggested" ? "## Suggested playbook" : "## Approach");
    if (blueprint.strategies_source === "suggested") {
      lines.push("A template from the goal target and domain. These are not recorded actions.");
    }
    for (const item of blueprint.strategies) lines.push(`- ${item}`);
  }
  const milestones = blueprint.milestones.map(milestoneText).filter((item): item is string => Boolean(item));
  if (milestones.length) {
    lines.push("", blueprint.milestones_source === "suggested" ? "## Suggested milestones" : "## Milestones");
    milestones.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
  }
  const tracked = blueprint.tracked_metrics ?? [];
  if (tracked.length) {
    lines.push("", "## Tracked metrics");
    for (const item of tracked) lines.push(`- ${item.replaceAll("_", " ")}`);
  }
  const updates = marketUpdates(market).slice(-ASSISTANT_SUMMARY_UPDATE_LIMIT).reverse();
  if (updates.length) {
    lines.push("", "## Recent published updates (newest first)");
    for (const update of updates) {
      const move = update.previous_probability != null && update.change_points != null
        ? `${percent(update.previous_probability)} → ${percent(update.probability)} (${signedPoints(update.change_points)})`
        : percent(update.probability);
      const context = updateContext(update);
      lines.push(`- ${formatShortDate(update.published_at)}: ${move}${context.length ? `. ${context.join("; ")}` : ""}`);
    }
  }
  const drivers = market.modeled_sensitivity?.drivers ?? [];
  if (drivers.length) {
    lines.push("", "## Modeled sensitivity (assumptions the model uses, not causes)");
    for (const item of drivers) lines.push(`- ${item}`);
  }
  return lines.join("\n");
}
