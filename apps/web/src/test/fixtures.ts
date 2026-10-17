import type { Goal } from "../api/client";

export const seededGoals: Goal[] = [
  {
    goal_id: "20000000-0000-0000-0000-000000000001",
    title: "Receive Waterloo Engineering admission",
    goal_type: "deadline_event",
    deadline: "2028-05-31T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["academic_performance"],
  },
  {
    goal_id: "20000000-0000-0000-0000-000000000002",
    title: "Receive a Big Tech or FDE offer",
    goal_type: "deadline_event",
    deadline: "2028-08-31T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["technical_interview"],
  },
  {
    goal_id: "20000000-0000-0000-0000-000000000003",
    title: "Reach one million dollars in net worth",
    goal_type: "continuous_target",
    deadline: "2035-12-31T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["liquid_assets"],
  },
  {
    goal_id: "20000000-0000-0000-0000-000000000004",
    title: "Run a 10K in under 50 minutes",
    goal_type: "threshold",
    deadline: "2028-06-30T23:59:59Z",
    forecast_status: "EXPLORATORY",
    state_dimensions: ["recent_race_time"],
  },
];
