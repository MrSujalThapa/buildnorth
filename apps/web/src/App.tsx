import { Route, Routes } from "react-router-dom";
import AppShell from "./components/shell/AppShell";
import SocialPage from "./components/utility/SocialPage";
import { NewGoalPage } from "./features/goals/NewGoalPage";
import { ComposioAuthLauncherPage } from "./pages/ComposioAuthLauncherPage";
import { EvidenceRoute } from "./pages/EvidenceRoute";
import { GoalDetailRoute } from "./pages/GoalDetailRoute";
import { MarketsRoute } from "./pages/MarketsRoute";
import { PluginsRoute } from "./pages/PluginsRoute";
import { SettingsRoute } from "./pages/SettingsRoute";
import { WhatIfRoute } from "./pages/WhatIfRoute";
import { ThemeProvider } from "./theme/ThemeProvider";

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<MarketsRoute />} />
      <Route path="/markets" element={<MarketsRoute />} />
      <Route path="/new" element={<NewGoalPage />} />
      <Route path="/goals/:goalId" element={<GoalDetailRoute />} />
      <Route path="/goals/:goalId/evidence" element={<EvidenceRoute />} />
      <Route path="/goals/:goalId/what-if" element={<WhatIfRoute />} />
      <Route path="/plugins" element={<PluginsRoute />} />
      <Route path="/social" element={<SocialPage />} />
      <Route path="/settings" element={<SettingsRoute />} />
      <Route path="*" element={<MarketsRoute />} />
    </Routes>
  );
}

export function App() {
  return (
    <ThemeProvider>
      <Routes>
        <Route path="/auth/composio/launch" element={<ComposioAuthLauncherPage />} />
        <Route
          path="*"
          element={
            <AppShell>
              <AppRoutes />
            </AppShell>
          }
        />
      </Routes>
    </ThemeProvider>
  );
}
