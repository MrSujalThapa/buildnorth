# Client capability matrix — Pass 06

Date: 2026-10-23. Vocabulary for this run: **PASS** / **FAIL** / **NOT TESTED**.

Local PASS means the official Python MCP SDK against in-process `/mcp` in this working tree (`test_remote_mcp_protocol.py`, `test_remote_mcp_pass05.py`, `test_remote_mcp_temporal.py`). It is not a ChatGPT or Grok session.

Production `https://playitout-api.onrender.com` answered OAuth discovery and challenged unauthenticated `GET /mcp` with 401. That server is the deployed `main` build, not this branch. No production tool call was made.

| Capability | ChatGPT Chat | ChatGPT Work | Grok Bot | MCP reference client |
|---|---|---|---|---|
| Connect / OAuth | NOT TESTED | NOT TESTED | NOT TESTED | PASS |
| Read goals | NOT TESTED | NOT TESTED | NOT TESTED | PASS |
| Create goals | NOT TESTED | NOT TESTED | NOT TESTED | PASS |
| Submit evidence | NOT TESTED | NOT TESTED | NOT TESTED | PASS |
| File transfer | NOT TESTED | NOT TESTED | NOT TESTED | PASS |
| What If | NOT TESTED | NOT TESTED | NOT TESTED | PASS |
| Historical odds | NOT TESTED | NOT TESTED | NOT TESTED | PASS |
| Interactive charts | NOT TESTED | NOT TESTED | NOT TESTED | PASS (protocol: `ui://playitout/odds-explorer` advertised) |
| Static chart fallback | NOT TESTED | NOT TESTED | NOT TESTED | PASS |
| Revocation | NOT TESTED | NOT TESTED | NOT TESTED | PASS |

Production discovery, not a tool call: protected-resource and authorization-server metadata **PASS** (HTTP 200, PKCE S256, revocation endpoint present). `GET /health` timed out at 40 seconds in the same probe and was not retried into a write.

ChatGPT and Grok were not opened. A Work result would not fill the Chat column. Grok Bot and grok.com connectors were not treated as the same product.

File transfer in the reference client is bounded CSV/XLSX/PDF bytes or structured rows. There is no URL fetch.

---

# Earlier matrix — 2026-10-19

Date: 2026-10-19. Status vocabulary: **PASS** / **FAIL** / **BLOCKED** / **NOT VERIFIED**.

Private HTTPS `/mcp` does not exist yet, so ChatGPT and Grok cannot be connected. Local SDK results are from Pass 05 + this pass’s OAuth tests against in-process FastAPI, **not** hosted staging.

Operator actions that produced each row are listed. No tokens, emails, or probabilities are copied here.

---

## ChatGPT — regular Chat

Account: the operator’s existing ChatGPT Plus. Surface: normal Chat, not Work, not a public plugin listing.

| Capability | Status | Evidence / operator action |
|---|---|---|
| OAuth PKCE + consent | BLOCKED | No public HTTPS `/mcp`. Not opened in chatgpt.com/plugins. |
| Read tools (`list_goals`, `get_goal`, `get_forecast`, history) | BLOCKED | Same |
| Write tools (`create_goal`, `continue_goal_creation`, evidence submit) | BLOCKED | Plus write-tool availability is also an undocumented-until-tested risk |
| File / structured transfer | BLOCKED | 40 KB file / structured-row fallback not exercised on this host |
| Historical queries (`compare_forecasts`) | BLOCKED | |
| What If (`compare_scenarios` / `simulate_intervention`) | BLOCKED | |
| Interactive Odds Explorer (MCP Apps) | BLOCKED | Must not be inferred from SDK HTML |
| Static PNG (`get_odds_chart_image`) | BLOCKED | |
| Revocation | BLOCKED | |
| Same-owner dashboard sync | BLOCKED | |

**Notes:** Do not publish the plugin. Test this row separately from Work after staging URLs exist. If the host only allows read/fetch, mark write tools FAIL with the host’s exact message, not a code defect, unless `/mcp` itself returns 403/400.

---

## ChatGPT — Work

Surface: Work with `@plugin` after the same custom MCP plugin is installed.

| Capability | Status | Evidence / operator action |
|---|---|---|
| OAuth PKCE + consent | BLOCKED | Work not opened |
| Read tools | BLOCKED | |
| Write tools | BLOCKED | OpenAI’s connect-and-test docs emphasize Work `@plugin`; still untested here |
| File / structured transfer | BLOCKED | |
| Historical queries | BLOCKED | |
| What If | BLOCKED | |
| Interactive charts | BLOCKED | |
| Static PNG | BLOCKED | |
| Revocation | BLOCKED | |
| Same-owner dashboard sync | BLOCKED | |

**Notes:** Regular Chat ≠ Work. A Work pass does not fill the Chat row.

---

## Grok Bot

Includes grok.com custom connectors and the Grok Bot plugin surface. They are not assumed equivalent.

| Capability | Status | Evidence / operator action |
|---|---|---|
| OAuth PKCE + consent | BLOCKED | `grok.com/connectors` and Grok Bot Settings → Plugins not used. DCR now locally accepts `cursor://anysphere.cursor-mcp/oauth/callback` plus HTTPS/localhost (pytest). Hosted DCR **NOT VERIFIED**. |
| Read tools | BLOCKED | |
| Write tools | BLOCKED | |
| File / structured transfer | BLOCKED | |
| Historical queries | BLOCKED | |
| What If | BLOCKED | |
| Interactive charts | BLOCKED | Do not assume MCP Apps |
| Static PNG / image content | BLOCKED | Host may ignore MCP image payloads |
| Revocation | BLOCKED | |
| Same-owner dashboard sync | BLOCKED | |

**Notes:** Grok Bot ≠ grok.com catalog connectors. After staging exists, record which product actually completed OAuth.

---

## Reference MCP SDK client

Official Python MCP SDK against PlayItOut `/mcp` (in-process harness, `iss=playitout-test` principals).

| Capability | Status | Evidence / operator action |
|---|---|---|
| OAuth PKCE + consent | PASS (local only) | `test_remote_mcp_oauth.py` / Pass 05 protocol tests. Hosted HTTPS SDK **NOT VERIFIED**. |
| Read tools | PASS (local only) | `test_remote_mcp_protocol.py`, Pass 05 tools |
| Write tools | PASS (local only) | `create_goal` / continue / structured evidence in `test_remote_mcp_pass05.py` (scripted inference) |
| File / structured transfer | PASS (local only) | Rows, table text, ≤40 KB file; oversize rejected; no URL fetch |
| Historical queries | PASS (local only) | `compare_forecasts` + Postgres receipt test |
| What If | PASS (local only) | `compare_scenarios` does not write history |
| Interactive charts | PASS (protocol only) | `ui://playitout/odds-explorer` advertised; no ChatGPT/Grok renderer |
| Static PNG | PASS (local only) | `get_odds_chart_image`; `docs/final/reports/odds-static.png` |
| Revocation | PASS (local only) | Revoked token → 401 |
| Same-owner dashboard sync | NOT VERIFIED | Requires hosted web + real Clerk owner |

**Notes:** Local PASS is not private-staging acceptance.

---

## Shared gates (all clients)

| Gate | Status |
|---|---|
| Two invited Clerk Google identities + one uninvited | NOT VERIFIED |
| Owner isolation across REST, MCP, files, forecasts | PASS in tests; live **NOT VERIFIED** |
| Published receipts survive API restart | PASS isolated E2E historically; hosted **NOT VERIFIED** |
| What If never writes baseline | PASS in tests; live **NOT VERIFIED** |
| Gmail → structured rows → same odds in dashboard and agent | BLOCKED |
| Caps `$25` / `$2` unchanged | PASS (config/tests); live spend **NOT VERIFIED** |

Until the operator returns HTTPS API, HTTPS web, and a reachable hosted Postgres, every ChatGPT/Grok cell stays **BLOCKED**.
