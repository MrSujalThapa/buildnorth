import { SignIn, useAuth, useClerk } from "@clerk/react";
import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useTheme } from "../theme/useTheme";
import { clerkAppearance } from "./clerkAppearance";
import "./auth.css";
import {
  capturePendingInvite,
  clearPendingInvite,
  clerkEnabled,
  invitePath,
  readTestToken,
  setAccessTokenProvider,
  type AccountView,
} from "./session";

const AccountContext = createContext<AccountView | null>(null);

export function useAccount(): AccountView | null {
  return useContext(AccountContext);
}

type Props = { children: ReactNode };

function Brand({ title, copy }: { title: string; copy: string }) {
  return (
    <>
      <p className="eyebrow">PLAY IT OUT</p>
      <h1>{title}</h1>
      <p className="auth-copy">{copy}</p>
    </>
  );
}

function InviteScreen({
  onRedeemed,
  onSignOut,
}: {
  onRedeemed: (account: AccountView) => void;
  onSignOut?: () => void;
}) {
  const navigate = useNavigate();
  const pending = capturePendingInvite() || "";
  const [token, setToken] = useState(pending);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(Boolean(pending));

  async function redeemValue(value: string) {
    setError(null);
    setBusy(true);
    try {
      const account = await api.redeemInvite(value.trim());
      clearPendingInvite();
      onRedeemed(account);
      navigate("/", { replace: true });
    } catch (caught) {
      setBusy(false);
      setError(caught instanceof Error ? caught.message : "Invitation could not be redeemed.");
    }
  }

  useEffect(() => {
    if (!pending) return;
    void redeemValue(pending);
    // One-shot auto-redeem after Google returns to the shared link.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="auth-screen">
      <section className="auth-panel">
        <Brand
          title={busy && !error ? "Redeeming" : "Invite only"}
          copy={
            busy && !error
              ? "Your Google account is signed in. Play It Out is granting access from the shared invitation now."
              : "This workspace is private. Open the shared invitation link you were sent. New Google accounts do not receive hosted inference until redemption succeeds."
          }
        />
        {busy && !error ? <p className="auth-status">Checking the invitation…</p> : null}
        {error ? <p className="auth-error">{error}</p> : null}
        {!busy || error ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void redeemValue(token.trim());
            }}
          >
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Invitation token"
              autoComplete="off"
              required
            />
            <button type="submit" disabled={busy}>
              {busy ? "Redeeming…" : "Redeem invitation"}
            </button>
          </form>
        ) : null}
        {onSignOut ? (
          <div className="auth-actions">
            <button type="button" className="auth-text-button" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function LoadingScreen() {
  return (
    <main className="auth-screen">
      <section className="auth-panel">
        <Brand title="Play It Out" copy="Checking your session." />
      </section>
    </main>
  );
}

function SessionErrorScreen({ message, onRetry, onSignOut }: { message: string; onRetry: () => void; onSignOut?: () => void }) {
  return (
    <main className="auth-screen">
      <section className="auth-panel">
        <Brand title="Session error" copy="Google signed you in, but Play It Out could not verify the session with the API." />
        <p className="auth-error">{message}</p>
        <button type="button" className="auth-primary" onClick={onRetry}>
          Try again
        </button>
        {onSignOut ? (
          <div className="auth-actions">
            <button type="button" className="auth-text-button" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function googleReturnUrl(): string {
  const pending = capturePendingInvite();
  if (pending) return `${window.location.origin}${invitePath(pending)}`;
  return window.location.href;
}

function ClerkGate({ children }: Props) {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { signOut } = useClerk();
  const { theme } = useTheme();
  const navigate = useNavigate();
  const [account, setAccount] = useState<AccountView | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [reload, setReload] = useState(0);
  const landed = useRef(false);
  const returnUrl = typeof window === "undefined" ? "/" : googleReturnUrl();

  useEffect(() => {
    setAccessTokenProvider(async () => (await getToken()) ?? null);
    return () => setAccessTokenProvider(null);
  }, [getToken]);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      setAccount(null);
      setSessionError(null);
      setReady(true);
      return;
    }
    let cancelled = false;
    void api
      .me()
      .then((next) => {
        if (cancelled) return;
        setAccount(next);
        setSessionError(null);
        setReady(true);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setAccount(null);
        setSessionError(caught instanceof Error ? caught.message : "Your session could not be verified.");
        setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, reload]);

  useEffect(() => {
    if (!account || landed.current) return;
    if (account.role === "admin" && !account.invited && !capturePendingInvite()) {
      landed.current = true;
      if (!window.location.pathname.startsWith("/settings")) {
        navigate("/settings", { replace: true });
      }
    }
  }, [account, navigate]);

  if (!isLoaded || !ready) return <LoadingScreen />;
  if (!isSignedIn) {
    return (
      <main className="auth-screen">
        <section className="auth-panel">
          <Brand
            title="Sign in"
            copy="Continue with Google. Access stays invite-only after your account is created, unless you are an allowlisted administrator."
          />
          <SignIn
            routing="hash"
            withSignUp
            appearance={clerkAppearance(theme)}
            forceRedirectUrl={returnUrl}
            fallbackRedirectUrl={returnUrl}
            signUpForceRedirectUrl={returnUrl}
            signUpFallbackRedirectUrl={returnUrl}
          />
        </section>
      </main>
    );
  }
  if (sessionError) {
    return (
      <SessionErrorScreen
        message={sessionError}
        onRetry={() => {
          setReady(false);
          setReload((value) => value + 1);
        }}
        onSignOut={() => {
          void signOut();
        }}
      />
    );
  }
  const pending = capturePendingInvite();
  if (account?.role === "admin") {
    return <AccountContext.Provider value={account}>{children}</AccountContext.Provider>;
  }
  if (!account?.invited) {
    return (
      <InviteScreen
        onRedeemed={setAccount}
        onSignOut={() => {
          void signOut();
        }}
      />
    );
  }
  if (pending) clearPendingInvite();
  return <AccountContext.Provider value={account}>{children}</AccountContext.Provider>;
}

function TokenGate({ children }: Props) {
  const token = readTestToken();
  const navigate = useNavigate();
  const [account, setAccount] = useState<AccountView | null>(null);
  const [ready, setReady] = useState(!token);

  useEffect(() => {
    if (!token) {
      setAccessTokenProvider(null);
      return;
    }
    setAccessTokenProvider(async () => readTestToken());
    let cancelled = false;
    void api
      .me()
      .then((next) => {
        if (cancelled) return;
        setAccount(next);
        setReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        setReady(true);
      });
    return () => {
      cancelled = true;
      setAccessTokenProvider(null);
    };
  }, [token]);

  useEffect(() => {
    if (account?.role === "admin" && !account.invited && !capturePendingInvite()) {
      if (!window.location.pathname.startsWith("/settings")) {
        navigate("/settings", { replace: true });
      }
    }
  }, [account, navigate]);

  if (!token) return children;
  if (!ready) return <LoadingScreen />;
  if (account?.role === "admin") {
    return <AccountContext.Provider value={account}>{children}</AccountContext.Provider>;
  }
  if (account && !account.invited) {
    return <InviteScreen onRedeemed={setAccount} />;
  }
  return <AccountContext.Provider value={account}>{children}</AccountContext.Provider>;
}

export function AuthGate({ children }: Props) {
  if (typeof window !== "undefined") capturePendingInvite();
  if (clerkEnabled()) return <ClerkGate>{children}</ClerkGate>;
  return <TokenGate>{children}</TokenGate>;
}
