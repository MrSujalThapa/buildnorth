# Pass 9A external-agent and GitHub evidence contract

## Agent requests

The existing remote MCP server remains the single entry point. Its server instructions and
tool descriptions distinguish a reported observation from a hypothetical question. Agents
should read goal and evidence policy before submitting an observation, ask for clarification
when goal, quantity, or time window is unclear, and obtain the user's confirmation before a
write. A hypothetical uses `simulate_intervention` and never submits evidence. A request
for past odds uses forecast history. Public blueprint search is not an exposed MCP tool;
agents must say so rather than invent results.

`get_forecast` and `get_forecast_history` expose publication status, model identity,
evidence watermark, publication time, and receipt identity. Evidence summaries expose
observation time and receipt time separately. A duplicate observation can corroborate an
existing evidence item, but does not publish another forecast receipt.

These are server contracts. The local MCP harness exercises protocol, OAuth, scopes,
tool schemas, reads, writes, duplicate handling, and owner isolation. It does not prove
that a particular Grok or ChatGPT host chooses the right tool from natural language.

## One source: GitHub commits

The existing approved GitHub read recipe, SourceWatch, job worker, normalizer, evidence
workflow, and baseline repricer are reused. A commit SHA is the stable raw identity;
repeated reads deduplicate. GitHub issues and pull requests are mutable, so their raw
identity includes a content fingerprint. A watch only reads a recipe for its own connected
account and resource. An expired, revoked, or changed connection blocks the read.
Provider cursors advance only after raw observations persist. A successful source read
may leave the forecast withheld when evidence is insufficient; that state is recorded
honestly in the job receipt. Transient provider failures retain the existing retry path.

The isolated GitHub fixture demonstrates two dated commits progressing through
normalization, evidence, and a legitimate baseline publication. The first observation
leaves the forecast withheld. The second supplies enough dated history to publish. A
repeat produces no new evidence or receipt. This fixture is not a live PlayItOut
Composio connection. Before a live demonstration, a user must authorize GitHub in
PlayItOut, select and approve the repository read, create the watch, and confirm that the
backend connection is active. No production evidence was submitted for this pass.

## Host acceptance boundary

Grok browser host validation requires a signed-in Grok session with the PlayItOut MCP
connector configured. ChatGPT normal Chat and Work should be checked separately using
the existing connected plugin; the SDK harness cannot establish their natural-language
routing. Neither host should be assumed to expose its other app connections to the
PlayItOut backend. No paid inference is needed for the local deterministic tests.
