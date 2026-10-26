import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bot, Link2, X } from "lucide-react";
import { api } from "../../api/client";
import { useAccount } from "../../auth/AuthGate";
import { absoluteUrl, buildAssistantSummary } from "../../features/social/share";

type Props = {
  goalId: string;
  onClose: () => void;
  /** Owner-only entry point to the publish confirmation. */
  onPublish?: () => void;
};

export const MCP_SETTINGS_PATH = "/settings#personal-agents-heading";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default function ShareDialog({ goalId, onClose, onPublish }: Props) {
  const account = useAccount();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const market = useQuery({
    queryKey: ["public-market", goalId],
    queryFn: ({ signal }) => api.publicMarket(goalId, signal),
  });
  const mcp = useQuery({
    queryKey: ["mcp-status"],
    queryFn: ({ signal }) => api.mcpStatus(signal),
    enabled: Boolean(account),
    retry: false,
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const item = market.data;
  const isPublic = item?.visibility === "public";
  const url = absoluteUrl(`/m/${goalId}`);
  const summary = useMemo(() => (item ? buildAssistantSummary(item, isPublic ? url : null) : ""), [item, isPublic, url]);
  const isOwner = Boolean(item && account?.user_id === item.creator.user_id);

  async function copySummary() {
    if (await copyText(summary)) {
      setNote("AI-assistant summary copied");
    } else {
      setPreviewOpen(true);
      setNote("Could not copy automatically. Select the preview text and copy it.");
    }
  }

  return (
    <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="share-title">
      <div className="confirm-card share-dialog">
        <header className="share-dialog-head">
          <h2 id="share-title">Share market</h2>
          <button type="button" className="forked-panel-close" onClick={onClose} aria-label="Close share options">
            <X size={15} aria-hidden="true" />
          </button>
        </header>
        {!item ? (
          <p role="status">{market.isError ? "Could not load this market." : "Loading…"}</p>
        ) : (
          <>
            <section className="share-option" aria-labelledby="share-link-title">
              <h3 id="share-link-title"><Link2 size={14} aria-hidden="true" /> Public market link</h3>
              {isPublic ? (
                <button
                  type="button"
                  className="ui-button ui-button-secondary"
                  onClick={() => { void copyText(url).then((ok) => setNote(ok ? "Link copied" : `Copy this link: ${url}`)); }}
                >
                  Copy public market link
                </button>
              ) : (
                <>
                  <p className="share-option-copy">This market is private. Publish it to get a public link.</p>
                  {isOwner && onPublish ? (
                    <button type="button" className="ui-button ui-button-secondary" onClick={onPublish}>Publish…</button>
                  ) : null}
                </>
              )}
            </section>

            <section className="share-option" aria-labelledby="share-summary-title">
              <h3 id="share-summary-title"><Bot size={14} aria-hidden="true" /> AI-assistant summary</h3>
              <p className="share-option-copy">
                A plain-text summary to paste into ChatGPT, Grok or another assistant: goal, success criteria, deadline,
                blueprint and published odds updates. Evidence details and credentials are never included.
              </p>
              {isPublic ? (
                <div className="share-option-actions">
                  <button type="button" className="ui-button" onClick={() => { void copySummary(); }}>Copy AI-assistant summary</button>
                  <button type="button" className="ui-button ui-button-secondary" aria-expanded={previewOpen} onClick={() => setPreviewOpen((open) => !open)}>
                    {previewOpen ? "Hide preview" : "Preview"}
                  </button>
                </div>
              ) : previewOpen ? (
                <div className="share-option-actions">
                  <button type="button" className="ui-button" onClick={() => { void copySummary(); }}>Copy this summary</button>
                </div>
              ) : (
                <div className="share-option-actions">
                  <button type="button" className="ui-button ui-button-secondary" onClick={() => setPreviewOpen(true)}>Review summary before copying</button>
                </div>
              )}
              {!isPublic && previewOpen ? (
                <p className="share-option-copy">This market is private. Only the text below will be copied.</p>
              ) : null}
              {previewOpen ? <pre className="share-summary-preview" aria-label="Summary preview" tabIndex={0}>{summary}</pre> : null}
            </section>

            {mcp.data?.enabled ? (
              <section className="share-option" aria-labelledby="share-mcp-title">
                <h3 id="share-mcp-title">Use in ChatGPT via MCP connector</h3>
                <p className="share-option-copy">
                  Connect Play It Out as a custom MCP server so the assistant can read your markets and odds after you approve access.
                </p>
                <Link className="ui-button ui-button-secondary" to={MCP_SETTINGS_PATH} onClick={onClose}>Open connector settings</Link>
              </section>
            ) : null}
          </>
        )}
        {note ? <p className="share-dialog-note" role="status">{note}</p> : null}
      </div>
    </div>
  );
}
