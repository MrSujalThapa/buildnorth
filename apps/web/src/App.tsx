import { ClerkProvider } from "@clerk/react";
import { Route, Routes } from "react-router-dom";
import { AuthGate } from "./auth/AuthGate";
import { clerkProviderLoadOptions, normalizePublishableKey } from "./auth/clerkScript";
import { clerkEnabled } from "./auth/session";
import AppShell from "./components/shell/AppShell";
import SocialPage from "./components/utility/SocialPage";
import { NewGoalPage } from "./features/goals/NewGoalPage";
import { ComposioAuthLauncherPage } from "./pages/ComposioAuthLauncherPage";
import { ConnectAuthorizePage } from "./pages/ConnectAuthorizePage";
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
      <Route path="/invite" element={<MarketsRoute />} />
      <Route path="/invite/:token" element={<MarketsRoute />} />
      <Route path="*" element={<MarketsRoute />} />
    </Routes>
  );
}

function AppTree() {
  return (
    <ThemeProvider>
      <Routes>
        <Route path="/auth/composio/launch" element={<ComposioAuthLauncherPage />} />
        <Route path="/connect/authorize" element={<AuthGate><ConnectAuthorizePage /></AuthGate>} />
        <Route
          path="*"
          element={
            <AuthGate>
              <AppShell>
                <AppRoutes />
              </AppShell>
            </AuthGate>
          }
        />
      </Routes>
    </ThemeProvider>
  );
}

export function App() {
  const publishableKey = normalizePublishableKey(import.meta.env.VITE_CLERK_PUBLISHABLE_KEY);
  if (clerkEnabled() && publishableKey) {
    return (
      <ClerkProvider publishableKey={publishableKey} {...clerkProviderLoadOptions(publishableKey, import.meta.env.VITE_CLERK_JS_URL)}>
        <AppTree />
      </ClerkProvider>
    );
  }
  return <AppTree />;
}
