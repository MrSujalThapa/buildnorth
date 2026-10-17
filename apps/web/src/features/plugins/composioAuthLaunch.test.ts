import { describe, expect, it } from "vitest";
import {
  composioAuthLauncherPath,
  isSafeHttpUrl,
  parseComposioAuthUrlMessage,
  parseComposioAuthUrlRequest,
} from "./composioAuthLaunch";

describe("composioAuthLaunch", () => {
  it("accepts only http(s) auth urls", () => {
    expect(isSafeHttpUrl("https://connect.composio.dev/link/abc")).toBe(true);
    expect(isSafeHttpUrl("http://localhost:5173/x")).toBe(true);
    expect(isSafeHttpUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeHttpUrl("not-a-url")).toBe(false);
  });

  it("parses valid auth messages and rejects malformed payloads", () => {
    const ok = parseComposioAuthUrlMessage({
      type: "pm.composio.auth_url",
      requestId: "req-1",
      authUrl: "https://connect.composio.dev/link/xyz",
    });
    expect(ok?.requestId).toBe("req-1");
    expect(parseComposioAuthUrlMessage({ type: "other" })).toBeNull();
    expect(
      parseComposioAuthUrlMessage({
        type: "pm.composio.auth_url",
        requestId: "req-1",
        authUrl: "javascript:alert(1)",
      }),
    ).toBeNull();
  });

  it("builds launcher path with encoded request id", () => {
    expect(composioAuthLauncherPath("abc/def")).toBe("/auth/composio/launch?id=abc%2Fdef");
  });

  it("parses launcher URL request messages", () => {
    expect(
      parseComposioAuthUrlRequest({ type: "pm.composio.auth_url_request", requestId: "req-9" })?.requestId,
    ).toBe("req-9");
    expect(parseComposioAuthUrlRequest({ type: "pm.composio.auth_url", requestId: "req-9" })).toBeNull();
  });
});
