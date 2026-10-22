import { lazy, Suspense } from "react";
import { ClerkProvider } from "@clerk/react";
import { Route, Routes } from "react-router-dom";
import { AuthGate } from "./auth/AuthGate";
import { clerkProviderLoadOptions, normalizePublishableKey } from "./auth/clerkScript";
import { clerkEnabled } from "./auth/session";
import AppShell from "./components/shell/AppShell";
import { MarketsRoute } from "./pages/MarketsRoute";
import { ThemeProvider } from "./theme/ThemeProvider";

const SocialPage = lazy(() => import("./components/utility/SocialPage"));
const NewGoalPage = lazy(() => import("./features/goals/NewGoalPage").then((module) => ({ default: module.NewGoalPage })));
const ComposioAuthLauncherPage = lazy(() => import("./pages/ComposioAuthLauncherPage").then((module) => ({ default: module.ComposioAuthLauncherPage })));
const ConnectAuthorizePage = lazy(() => import("./pages/ConnectAuthorizePage").then((module) => ({ default: module.ConnectAuthorizePage })));
const CollectionDetailRoute = lazy(() => import("./pages/CollectionDetailRoute").then((module) => ({ default: module.CollectionDetailRoute })));
const EvidenceRoute = lazy(() => import("./pages/EvidenceRoute").then((module) => ({ default: module.EvidenceRoute })));
const GoalDetailRoute = lazy(() => import("./pages/GoalDetailRoute").then((module) => ({ default: module.GoalDetailRoute })));
const PluginsRoute = lazy(() => import("./pages/PluginsRoute").then((module) => ({ default: module.PluginsRoute })));
const ProfileRoute = lazy(() => import("./pages/ProfileRoute").then((module) => ({ default: module.ProfileRoute })));
const SettingsRoute = lazy(() => import("./pages/SettingsRoute").then((module) => ({ default: module.SettingsRoute })));
const WhatIfRoute = lazy(() => import("./pages/WhatIfRoute").then((module) => ({ default: module.WhatIfRoute })));

function AppRoutes() {
  return (
    <Suspense fallback={<main className="route-loading" role="status">Loading…</main>}><Routes>
      <Route path="/" element={<MarketsRoute />} />
      <Route path="/markets" element={<MarketsRoute />} />
      <Route path="/new" element={<NewGoalPage />} />
      <Route path="/goals/:goalId" element={<GoalDetailRoute />} />
      <Route path="/goals/:goalId/evidence" element={<EvidenceRoute />} />
      <Route path="/goals/:goalId/what-if" element={<WhatIfRoute />} />
      <Route path="/collections/:collectionId" element={<CollectionDetailRoute />} />
      <Route path="/plugins" element={<PluginsRoute />} />
      <Route path="/social" element={<SocialPage />} />
      <Route path="/profile" element={<ProfileRoute />} />
      <Route path="/settings" element={<SettingsRoute />} />
      <Route path="/invite" element={<MarketsRoute />} />
      <Route path="/invite/:token" element={<MarketsRoute />} />
      <Route path="*" element={<MarketsRoute />} />
    </Routes></Suspense>
  );
}

function AppTree() {
  return (
    <ThemeProvider>
      <Suspense fallback={<main className="route-loading" role="status">Loading…</main>}><Routes>
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
      </Routes></Suspense>
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
