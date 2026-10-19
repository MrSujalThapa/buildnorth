import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api, type InferenceSettings as Settings } from "../../api/client";
import { InferenceSettings } from "./InferenceSettings";

afterEach(() => vi.restoreAllMocks());

test("connecting a key activates BYOK and displays remaining hosted credit", async () => {
  let mode: "hosted" | "byok" = "hosted";
  const settings = (): Settings => ({
    preference: { mode, provider: "openai", model: null },
    credentials: mode === "byok" ? [{ provider: "openai", status: "validated", masked_suffix: "••••1234", version: "v", validated_at: "2026-10-19T00:00:00Z" }] : [],
    models: [], hosted_provider: "openai", hosted_model: "gpt-5.4-mini",
    byok_usage: { calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
  });
  vi.spyOn(api, "inferenceSettings").mockImplementation(() => Promise.resolve(settings()));
  vi.spyOn(api, "saveInferencePreference");
  vi.spyOn(api, "saveProviderKey").mockImplementation(() => {
    mode = "byok";
    return Promise.resolve({ provider: "openai", status: "validated", masked_suffix: "••••1234", version: "v", validated_at: "2026-10-19T00:00:00Z" });
  });
  render(<InferenceSettings hosted={{ enabled: true, quota_usd: 5, remaining_usd: 4.73, global_remaining_usd: 99, kill_switch: false, quota_tokens: 0, reserved_usd: 0, spent_usd: 0, reserved_tokens: 0, spent_tokens: 0, remaining_tokens: 0, billing_note: "" }} />);
  expect(await screen.findByText(/Hosted credit: \$4\.73 \/ \$5\.00 remaining/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-test-key-1234" } });
  fireEvent.click(screen.getByRole("button", { name: "Add and validate key" }));
  await waitFor(() => expect(screen.getByText(/BYOK is now active/)).toBeInTheDocument());
  expect(screen.getByText("Current mode: BYOK")).toBeInTheDocument();
  expect(api.saveProviderKey).toHaveBeenCalledTimes(1);
  expect(api.saveInferencePreference).not.toHaveBeenCalled();
});
