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

export function filterHistoryForRange(
  history: ChartPoint[],
  range: MarketRange,
): ChartPoint[] {
  if (
    history.length === 0 ||
    range.unit === "all"
  ) {
    return history;
  }

  const latest =
    history[
      history.length - 1
    ];

  if (
    !latest ||
    range.amount === undefined
  ) {
    return history;
  }

  const unitMs: Record<
    Exclude<
      RangeUnit,
      "all"
    >,
    number
  > = {
    hour: HOUR,
    day: DAY,
    week: WEEK,
    month: MONTH,
    year: YEAR,
  };

  const cutoff =
    latest.timestamp -
    unitMs[range.unit] *
      range.amount;

  const filtered =
    history.filter(
      (point) =>
        point.timestamp >=
        cutoff,
    );

  return filtered.length
    ? filtered
    : history.slice(-1);
}
