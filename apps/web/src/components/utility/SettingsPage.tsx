import { Copy, Link2, Moon, ShieldCheck, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type InvitationRecord } from "../../api/client";
import { useAccount } from "../../auth/AuthGate";
import { invitePath } from "../../auth/session";
import "./utility-pages.css";
import { InferenceSettings } from "./InferenceSettings";
import { PersonalAgents } from "./PersonalAgents";

type Props = {
  theme: "light" | "dark";
  onSetTheme: (theme: "light" | "dark") => void;
};

function money(value: number): string {
  return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

export default function SettingsPage({ theme, onSetTheme }: Props) {
  const account = useAccount();
  const [hosted, setHosted] = useState(account?.hosted);
  const [usageError, setUsageError] = useState<string | null>(null);
  useEffect(() => {
    if (!account) return;
    let cancelled = false;
    void api.me().then((next) => {
      if (!cancelled) setHosted(next.hosted);
    }).catch(() => {
      if (!cancelled) setUsageError("Hosted usage could not be refreshed. Reload to try again.");
    });
    return () => { cancelled = true; };
  }, [account]);
  return (
    <main className="utility-page">
      <section className="utility-shell">
        <header className="utility-header">
          <h1>Settings</h1>
          <p>
            {account?.role === "admin"
              ? "Generate a shared invitation, then check hosted allowance and appearance."
              : "Control how Play It Out looks, connects data, and uses evidence."}
          </p>
        </header>

        {account?.role === "admin" ? <InviteAdmin /> : null}

        <section className="settings-group">
          <h2>Account</h2>
          <div className="settings-list">
            <div className="setting-row">
              <div>
                <strong>{account?.email || "Local session"}</strong>
                <span>
                  {account
                    ? `${account.role === "admin" ? "Administrator" : "Invited member"}${account.email_verified ? " · verified email" : ""}`
                    : "Sign in with Clerk to bind this workspace to your account."}
                </span>
              </div>
            </div>
            <div className="setting-row">
              <div>
                <strong>Hosted inference</strong>
                <span>
                  {hosted
                    ? `${money(hosted.remaining_usd)} remaining of ${money(hosted.quota_usd)} · ${hosted.remaining_tokens.toLocaleString()} tokens left`
                    : "Sign in to see your hosted Spur allowance."}
                </span>
              </div>
            </div>
            {hosted ? (
              <p className="setting-note">{hosted.billing_note}</p>
            ) : null}
            {usageError ? <p className="setting-note" role="alert">{usageError}</p> : null}
          </div>
        </section>

        <InferenceSettings />

        <PersonalAgents />

        <section className="settings-group">
          <h2>Appearance</h2>
          <div className="theme-choice-row">
            <button
              type="button"
              className={theme === "light" ? "theme-choice selected" : "theme-choice"}
              onClick={() => onSetTheme("light")}
            >
              <Sun size={19} />
              <span><strong>Light</strong><small>Warm white interface</small></span>
            </button>
            <button
              type="button"
              className={theme === "dark" ? "theme-choice selected" : "theme-choice"}
              onClick={() => onSetTheme("dark")}
            >
              <Moon size={19} />
              <span><strong>Dark</strong><small>Near-black interface</small></span>
            </button>
          </div>
        </section>

        <section className="settings-group">
          <h2>Evidence & data</h2>
          <div className="settings-list">
            <div className="setting-row">
              <div>
                <strong>Automatic evidence suggestions</strong>
                <span>Surface useful observations from connected plugins before they affect a goal.</span>
              </div>
              <label className="setting-switch"><input type="checkbox" defaultChecked /><span /></label>
            </div>
            <div className="setting-row">
              <div>
                <strong>Require review for sensitive evidence</strong>
                <span>Health, financial, and ambiguous observations stay pending until approved.</span>
              </div>
              <label className="setting-switch"><input type="checkbox" defaultChecked /><span /></label>
            </div>
            <div className="setting-row">
              <div>
                <strong>Show provenance on evidence</strong>
                <span>Keep the source plugin, timestamp, and original record attached to every observation.</span>
              </div>
              <label className="setting-switch"><input type="checkbox" defaultChecked /><span /></label>
            </div>
          </div>
        </section>

        <section className="privacy-note">
          <ShieldCheck size={20} />
          <div>
            <strong>Connected data should never change odds by itself.</strong>
            <p>Plugins produce source observations. Play It Out decides whether those observations are relevant evidence for a goal, preserves provenance, and only then reprices the market.</p>
          </div>
        </section>
      </section>
    </main>
  );
}

function inviteUrl(token: string): string {
  return `${window.location.origin}${invitePath(token)}`;
}

function InviteAdmin() {
  const [invites, setInvites] = useState<InvitationRecord[]>([]);
  const [sessionUrls, setSessionUrls] = useState<Record<string, string>>({});
  const [ttlHours, setTtlHours] = useState(72);
  const [maxRedemptions, setMaxRedemptions] = useState(20);
  const [note, setNote] = useState("Hackathon access");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setInvites(await api.listInvites());
  }

  useEffect(() => {
    void refresh().catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : "Could not load invitations.");
    });
  }, []);

  async function generate(replaceId?: string) {
    setError(null);
    setBusy(true);
    try {
      if (replaceId) {
        await api.revokeInvite(replaceId);
        setSessionUrls((current) => {
          const next = { ...current };
          delete next[replaceId];
          return next;
        });
      }
      const created = await api.createInvite({
        note: note.trim() || "Hackathon access",
        ttl_hours: ttlHours,
        max_redemptions: maxRedemptions,
      });
      if (!created.token) throw new Error("Invitation token was not returned.");
      const url = inviteUrl(created.token);
      setSessionUrls((current) => ({ ...current, [created.invitation_id]: url }));
      // Clipboard permission may stay pending. Creation and revocation must not depend on it.
      setCopiedId(null);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Invitation could not be created.");
    } finally {
      setBusy(false);
    }
  }

  async function copy(invitationId: string, url: string) {
    setError(null);
    try {
      await navigator.clipboard.writeText(url);
      setCopiedId(invitationId);
    } catch {
      setError("Could not copy the invitation. Select and copy the displayed URL, or reload and generate a replacement.");
    }
  }

  async function revoke(invitationId: string) {
    setError(null);
    try {
      await api.revokeInvite(invitationId);
      setSessionUrls((current) => {
        const next = { ...current };
        delete next[invitationId];
        return next;
      });
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Invitation could not be revoked.");
    }
  }

  return (
    <section className="settings-group">
      <h2>Invitations</h2>
      <div className="settings-list">
        <div className="setting-row">
          <div>
            <strong>Shared hackathon link</strong>
            <span>
              You do not need a personal invitation. Generate one link for up to {maxRedemptions}{" "}
              distinct Google accounts. Play It Out stores only a hash of the token, so copy the URL
              while this page is open — a reload cannot recover it.
            </span>
          </div>
        </div>
      </div>
      <form
        className="invite-admin-form"
        onSubmit={(event) => {
          event.preventDefault();
          void generate();
        }}
      >
        <label>
          Note
          <input value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
        <label>
          Expires in hours
          <input
            type="number"
            min={1}
            max={720}
            value={ttlHours}
            onChange={(event) => setTtlHours(Number(event.target.value))}
          />
        </label>
        <label>
          Maximum redemptions
          <input
            type="number"
            min={1}
            max={20}
            value={maxRedemptions}
            onChange={(event) => setMaxRedemptions(Number(event.target.value))}
          />
        </label>
        <button type="submit" disabled={busy}>
          <Link2 size={16} />
          {busy ? "Generating…" : "Generate link"}
        </button>
      </form>
      {error ? <p className="setting-note">{error}</p> : null}
      <div className="invite-list">
        {invites.length === 0 ? (
          <p className="setting-note">No invitations yet.</p>
        ) : (
          invites.map((invite) => {
            const status = invite.revoked_at
              ? "Revoked"
              : invite.redeemed_at
                ? "Filled"
                : "Open";
            const url = sessionUrls[invite.invitation_id];
            return (
              <div key={invite.invitation_id} className="invite-row">
                <div>
                  <strong>{invite.kind === "shared" ? "Shared link" : invite.email || "Email invite"}</strong>
                  <span>
                    {invite.redemption_count}/{invite.max_redemptions} redeemed · {status}
                    {invite.note ? ` · ${invite.note}` : ""} · expires{" "}
                    {new Date(invite.expires_at).toLocaleString()}
                  </span>
                  {url ? (
                    <div className="invite-created">
                      <code>{url}</code>
                      <button type="button" onClick={() => void copy(invite.invitation_id, url)}>
                        <Copy size={15} />
                        {copiedId === invite.invitation_id ? "Copied" : "Copy"}
                      </button>
                    </div>
                  ) : status === "Open" ? (
                    <span>
                      The full URL cannot be recovered after a reload. Generate a replacement or
                      revoke this invitation.
                    </span>
                  ) : null}
                </div>
                {status === "Open" ? (
                  <div className="invite-row-actions">
                    {url ? null : (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void generate(invite.invitation_id)}
                      >
                        Generate replacement
                      </button>
                    )}
                    <button type="button" onClick={() => void revoke(invite.invitation_id)}>
                      Revoke
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
