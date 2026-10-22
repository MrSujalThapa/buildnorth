export type AreaGoal = { goal_id: string; title: string };
export type ProfileArea = { label: string; goal_ids: string[] };

export const COMMON_AREAS = [
  "Reading",
  "Coding",
  "Fitness",
  "Sports",
  "Music",
  "School",
  "Career",
  "Creativity",
  "Personal",
  "Time management",
] as const;

const HINTS: Record<string, string[]> = {
  Reading: ["read", "book", "reading"],
  Coding: ["code", "coding", "leetcode", "github", "program"],
  Fitness: ["fitness", "gym", "workout", "run", "training"],
  Sports: ["sport", "team", "match", "game"],
  Music: ["music", "piano", "guitar", "practice", "song"],
  School: ["school", "class", "course", "homework", "study", "exam"],
  Career: ["career", "job", "interview", "application", "resume"],
  Creativity: ["creative", "art", "design", "write", "writing"],
  Personal: ["personal", "habit", "health"],
  "Time management": ["time", "schedule", "calendar", "focus"],
};

export function areaMatches(label: string, title: string): boolean {
  const hints = HINTS[label] ?? [label.toLowerCase()];
  const haystack = title.toLowerCase();
  return hints.some((hint) => haystack.includes(hint));
}

export function suggestAreas(goals: AreaGoal[], existing: string[]): string[] {
  const have = new Set(existing.map((item) => item.trim().toLowerCase()).filter(Boolean));
  const matched = COMMON_AREAS.filter(
    (area) => !have.has(area.toLowerCase()) && goals.some((goal) => areaMatches(area, goal.title)),
  );
  const extras = COMMON_AREAS.filter(
    (area) => !have.has(area.toLowerCase()) && !matched.includes(area),
  );
  return [...matched, ...extras].slice(0, 8);
}

export function linkedGoals(label: string, goals: AreaGoal[]): {
  ids: string[];
  titles: string[];
  ambiguous: boolean;
} {
  const hits = goals.filter((goal) => areaMatches(label, goal.title));
  const only = hits[0];
  if (hits.length === 1 && only) {
    return { ids: [only.goal_id], titles: [only.title], ambiguous: false };
  }
  if (hits.length > 1) {
    return { ids: [], titles: hits.map((goal) => goal.title), ambiguous: true };
  }
  return { ids: [], titles: [], ambiguous: false };
}

export function resolveAreas(areas: ProfileArea[], goals: AreaGoal[]): ProfileArea[] {
  return areas
    .map((area) => ({ ...area, label: area.label.trim() }))
    .filter((area) => area.label)
    .map((area) => {
      if (area.goal_ids.length) return area;
      const linked = linkedGoals(area.label, goals);
      return linked.ambiguous ? area : { ...area, goal_ids: linked.ids };
    });
}
