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
    models: [], discovered_models: {}, recommended_model: "gpt-5.4-mini", hosted_provider: "spur", hosted_configured: false, hosted_model: "spur-glm-5-3",
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
  expect(screen.getAllByText(/Hosted provider not configured/).length).toBeGreaterThan(0);
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-test-key-1234" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect and use my key" }));
  await waitFor(() => expect(screen.getByText(/BYOK is now active/)).toBeInTheDocument());
  expect(screen.getByText("Current mode: BYOK")).toBeInTheDocument();
  expect(api.saveProviderKey).toHaveBeenCalledTimes(1);
  expect(api.saveInferencePreference).not.toHaveBeenCalled();
});

test("hosted Spur model is never submitted as an Anthropic BYOK model", async () => {
  const settings: Settings = {
    preference: { mode: "hosted", provider: "anthropic", model: null },
    credentials: [{ provider: "anthropic", status: "validated", masked_suffix: "••••1234", version: "v", validated_at: "2026-10-19T00:00:00Z" }],
    models: [],
    discovered_models: { anthropic: [] },
    recommended_model: "spur-glm-5-3",
    hosted_provider: "spur",
    hosted_configured: true,
    hosted_model: "spur-glm-5-3",
    byok_usage: { calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 },
  };
  vi.spyOn(api, "inferenceSettings").mockResolvedValue(settings);
  const save = vi.spyOn(api, "saveInferencePreference").mockResolvedValue(settings);
  render(<InferenceSettings />);
  expect(await screen.findByRole("button", { name: "Save BYOK preference" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Provider default" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Save BYOK preference" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith({ mode: "byok", provider: "anthropic", model: null }));
});
