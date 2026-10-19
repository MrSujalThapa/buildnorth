import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import { ThemeProvider } from "../theme/ThemeProvider";
import { AuthGate } from "./AuthGate";
import * as session from "./session";

const clerk = vi.hoisted(() => ({ getToken: vi.fn(() => Promise.resolve("regression-test-token")), signOut: vi.fn() }));
vi.mock("@clerk/react", () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: clerk.getToken }),
  useClerk: () => ({ signOut: clerk.signOut }),
  SignIn: () => null,
}));

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  session.setAccessTokenProvider(null);
});

function Location() {
  return <p data-testid="location">{useLocation().pathname}</p>;
}

for (const mode of ["clerk", "token"] as const) {
  for (const path of ["/new", "/markets", "/goals/owner-goal", "/goals/owner-goal/what-if", "/settings", "/connect/authorize", "/"]) {
    test(`${mode} administrator preserves ${path} on initial load and refresh`, async () => {
      vi.spyOn(session, "clerkEnabled").mockReturnValue(mode === "clerk");
      vi.spyOn(session, "readTestToken").mockReturnValue("regression-test-token");
      vi.spyOn(api, "me").mockResolvedValue({
        user_id: "admin", clerk_user_id: "clerk-admin", email: "admin@example.test",
        email_verified: true, role: "admin", invited: false,
        hosted: {} as session.HostedUsage,
      });
      const expected = path === "/" ? "/settings" : path;
      const mount = () => render(
        <MemoryRouter initialEntries={[path]}>
          <ThemeProvider><AuthGate><Location /></AuthGate></ThemeProvider>
        </MemoryRouter>,
      );
      for (let load = 0; load < 2; load++) {
        window.history.replaceState({}, "", path);
        const view = mount();
        await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(expected));
        view.unmount();
      }
    });
  }
}
