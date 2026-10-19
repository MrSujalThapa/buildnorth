import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api, type InvitationRecord } from "../../api/client";
import type { AccountView } from "../../auth/session";
import SettingsPage from "./SettingsPage";

vi.mock("../../auth/AuthGate", () => ({ useAccount: () => ({ role: "admin", hosted: null }) }));
vi.mock("./InferenceSettings", () => ({ InferenceSettings: () => null }));
vi.mock("./PersonalAgents", () => ({ PersonalAgents: () => null }));
afterEach(() => vi.restoreAllMocks());

test("invitation creation and revocation work even when clipboard permission never resolves", async () => {
  const writeText = vi.fn(() => new Promise<void>(() => {}));
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const invites: InvitationRecord[] = [];
  vi.spyOn(api, "me").mockResolvedValue({ hosted: null } as unknown as AccountView);
  vi.spyOn(api, "listInvites").mockImplementation(() => Promise.resolve([...invites]));
  vi.spyOn(api, "createInvite").mockImplementation(() => {
    const row: InvitationRecord = {
      invitation_id: "test-invite", email: null, note: "Regression", kind: "shared",
      max_redemptions: 1, redemption_count: 0, hosted_quota_usd: 0, hosted_quota_tokens: 0,
      expires_at: "2027-01-01T00:00:00Z", revoked_at: null, redeemed_at: null,
    };
    invites.push(row);
    return Promise.resolve({ ...row, token: "fake-regression-invite-token" });
  });
  vi.spyOn(api, "revokeInvite").mockImplementation(() => {
    const row = invites[0];
    if (!row) throw new Error("Test invitation missing");
    row.revoked_at = "2026-10-19T22:00:00Z";
    return Promise.resolve(row);
  });
  render(<MemoryRouter><SettingsPage theme="light" onSetTheme={vi.fn()} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "Generate link" }));
  expect(await screen.findByRole("button", { name: "Revoke" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Generate link" })).toBeEnabled();
  expect(writeText).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: /^Copy$/ })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
  await waitFor(() => expect(screen.getByText(/redeemed · Revoked/)).toBeInTheDocument());
  expect(screen.queryByText(/fake-regression-invite-token/)).not.toBeInTheDocument();
});
