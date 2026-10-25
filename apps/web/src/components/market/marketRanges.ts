import type { ChartPoint, Market } from "../../adapters/templateTypes";

export type RangeUnit =
  | "hour"
  | "day"
  | "week"
  | "month"
  | "year"
  | "all";

export type MarketRange = {
  label: string;
  amount?: number;
  unit: RangeUnit;
};

const HOUR =
  60 * 60 * 1000;

const DAY =
  24 * HOUR;

const WEEK =
  7 * DAY;

const MONTH =
  30 * DAY;

const YEAR =
  365 * DAY;

export const ODDS_EXPLORER_RANGES: MarketRange[] = [
  { label: "1D", amount: 1, unit: "day" },
  { label: "1W", amount: 1, unit: "week" },
  { label: "1M", amount: 1, unit: "month" },
  { label: "1Y", amount: 1, unit: "year" },
  { label: "ALL", unit: "all" },
];

export function getMarketRanges(
  market: Market,
): MarketRange[] {
  const horizon =
    market.deadlineAt -
    market.createdAt;

  const days =
    horizon / DAY;

  /*
    ~1 week goal
  */
  if (days <= 8) {
    return [
      {
        label: "1H",
        amount: 1,
        unit: "hour",
      },
      {
        label: "6H",
        amount: 6,
        unit: "hour",
      },
      {
        label: "1D",
        amount: 1,
        unit: "day",
      },
      {
        label: "2D",
        amount: 2,
        unit: "day",
      },
      {
        label: "3D",
        amount: 3,
        unit: "day",
      },
      {
        label: "ALL",
        unit: "all",
      },
    ];
  }

  /*
    Up to 1 month
  */
  if (days <= 31) {
    return [
      {
        label: "6H",
        amount: 6,
        unit: "hour",
      },
      {
        label: "1D",
        amount: 1,
        unit: "day",
      },
      {
        label: "3D",
        amount: 3,
        unit: "day",
      },
      {
        label: "1W",
        amount: 1,
        unit: "week",
      },
      {
        label: "2W",
        amount: 2,
        unit: "week",
      },
      {
        label: "ALL",
        unit: "all",
      },
    ];
  }

  /*
    Up to 3 months
  */
  if (days <= 100) {
    return [
      {
        label: "1D",
        amount: 1,
        unit: "day",
      },
      {
        label: "3D",
        amount: 3,
        unit: "day",
      },
      {
        label: "1W",
        amount: 1,
        unit: "week",
      },
      {
        label: "2W",
        amount: 2,
        unit: "week",
      },
      {
        label: "1M",
        amount: 1,
        unit: "month",
      },
      {
        label: "ALL",
        unit: "all",
      },
    ];
  }

  /*
    Up to 6 months
  */
  if (days <= 190) {
    return [
      {
        label: "1D",
        amount: 1,
        unit: "day",
      },
      {
        label: "1W",
        amount: 1,
        unit: "week",
      },
      {
        label: "2W",
        amount: 2,
        unit: "week",
      },
      {
        label: "1M",
        amount: 1,
        unit: "month",
      },
      {
        label: "3M",
        amount: 3,
        unit: "month",
      },
      {
        label: "ALL",
        unit: "all",
      },
    ];
  }

  /*
    Up to 1 year
  */
  if (days <= 370) {
    return [
      {
        label: "1D",
        amount: 1,
        unit: "day",
      },
      {
        label: "1W",
        amount: 1,
        unit: "week",
      },
      {
        label: "1M",
        amount: 1,
        unit: "month",
      },
      {
        label: "3M",
        amount: 3,
        unit: "month",
      },
      {
        label: "6M",
        amount: 6,
        unit: "month",
      },
      {
        label: "ALL",
        unit: "all",
      },
    ];
  }

  /*
    Up to 3 years
  */
  if (days <= 365 * 3) {
    return [
      {
        label: "1W",
        amount: 1,
        unit: "week",
      },
      {
        label: "1M",
        amount: 1,
        unit: "month",
      },
      {
        label: "3M",
        amount: 3,
        unit: "month",
      },
      {
        label: "6M",
        amount: 6,
        unit: "month",
      },
      {
        label: "1Y",
        amount: 1,
        unit: "year",
      },
      {
        label: "ALL",
        unit: "all",
      },
    ];
  }

  /*
    Up to 5 years
  */
  if (days <= 365 * 5) {
    return [
      {
        label: "1W",
        amount: 1,
        unit: "week",
      },
      {
        label: "1M",
        amount: 1,
        unit: "month",
      },
      {
        label: "3M",
        amount: 3,
        unit: "month",
      },
      {
        label: "1Y",
        amount: 1,
        unit: "year",
      },
      {
        label: "3Y",
        amount: 3,
        unit: "year",
      },
      {
        label: "ALL",
        unit: "all",
      },
    ];
  }

  return [
    {
      label: "1M",
      amount: 1,
      unit: "month",
    },
    {
      label: "3M",
      amount: 3,
      unit: "month",
    },
    {
      label: "1Y",
      amount: 1,
      unit: "year",
    },
    {
      label: "3Y",
      amount: 3,
      unit: "year",
    },
    {
      label: "5Y",
      amount: 5,
      unit: "year",
    },
    {
      label: "ALL",
      unit: "all",
    },
  ];
}

const UNIT_MS: Record<Exclude<RangeUnit, "all">, number> = {
  hour: HOUR,
  day: DAY,
  week: WEEK,
  month: MONTH,
  year: YEAR,
};

export type RangeWindow = {
  /** Published points inside the window, plus flagged carry points at its edges. */
  points: ChartPoint[];
  /** Published forecasts that fall inside the window. */
  updates: number;
  /** The forecast standing at the window start, published before it. */
  standing: ChartPoint | null;
};

/**
 * Forecasts are step functions: a published value holds until the next publication.
 * The window ends at `now`; the value standing at its start is carried in and the latest
 * value is held to `now`, both marked `carried`, so the chart never collapses to a point.
 */
export function rangeWindow(
  history: ChartPoint[],
  range: MarketRange,
  now: number = Date.now(),
): RangeWindow {
  const sorted = [...history].sort((a, b) => a.timestamp - b.timestamp);
  const latest = sorted[sorted.length - 1];
  if (!latest) return { points: [], updates: 0, standing: null };
  const end = Math.max(now, latest.timestamp);
  const start =
    range.unit === "all" || range.amount === undefined
      ? sorted[0]!.timestamp
      : end - UNIT_MS[range.unit] * range.amount;
  const inside = sorted.filter((point) => point.timestamp >= start && point.timestamp <= end);
  const before = sorted.filter((point) => point.timestamp < start);
  const standing = before[before.length - 1] ?? null;
  const points: ChartPoint[] = [];
  if (standing) points.push({ timestamp: start, value: standing.value, carried: true });
  points.push(...inside);
  const last = points[points.length - 1] ?? latest;
  if (last.timestamp < end) points.push({ timestamp: end, value: last.value, carried: true });
  if (points.length === 1) {
    const only = points[0]!;
    points.unshift({ timestamp: only.timestamp - HOUR, value: only.value, carried: true });
  }
  return { points, updates: inside.length, standing };
}

export function filterHistoryForRange(
  history: ChartPoint[],
  range: MarketRange,
  now: number = Date.now(),
): ChartPoint[] {
  return rangeWindow(history, range, now).points;
}
