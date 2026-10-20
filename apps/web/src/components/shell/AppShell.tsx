import { useLocation, useNavigate } from "react-router-dom";
import { ChartNoAxesCombined, Moon, Plug, Settings, Sun, UserRound, Users } from "lucide-react";
import type { ReactNode } from "react";
import { useAccount } from "../../auth/AuthGate";
import { useTheme } from "../../theme/useTheme";
import "./app-shell.css";

type Props = { children: ReactNode };

const items = [
  { id: "market", label: "Market", Icon: ChartNoAxesCombined, path: "/markets" },
  { id: "plugins", label: "Plugins", Icon: Plug, path: "/plugins" },
  { id: "social", label: "Social", Icon: Users, path: "/social" },
  { id: "settings", label: "Settings", Icon: Settings, path: "/settings" },
] as const;

function activeFromPath(pathname: string) {
  if (pathname.startsWith("/plugins")) return "plugins";
  if (pathname.startsWith("/social")) return "social";
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/profile")) return "profile";
  return "market";
}

export default function AppShell({ children }: Props) {
  const location = useLocation();
  const navigate = useNavigate();
  const active = activeFromPath(location.pathname);
  const { theme, toggle } = useTheme();
  const account = useAccount();
  const profileLabel =
    account?.profile?.username || account?.profile?.display_name || account?.email?.split("@")[0] || "Profile";

  return (
    <div className={`app-shell theme-${theme}`}>
      <a className="skip-link" href="#app-main">Skip to main content</a>
      <aside className="app-sidebar">
        <button className="brand" type="button" onClick={() => { void navigate("/markets"); }} aria-label="Play It Out, go to Market">
          <span>Play It Out</span><b>PIO</b>
        </button>
        <nav aria-label="Primary navigation">
          {items.map(({ id, label, Icon, path }) => (
            <button
              key={id}
              type="button"
              className={active === id ? "active" : ""}
              aria-current={active === id ? "page" : undefined}
              onClick={() => { void navigate(path); }}
            >
              <Icon size={19} strokeWidth={1.7} /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button type="button" onClick={toggle} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}>
            {theme === "light" ? <Moon size={19} /> : <Sun size={19} />}<span>Theme</span>
          </button>
          <button type="button" onClick={() => { void navigate("/profile"); }} aria-label="Open profile" aria-current={active === "profile" ? "page" : undefined}>
            <UserRound size={19} /><span>{profileLabel}</span>
          </button>
        </div>
      </aside>
      <div className="app-content" id="app-main">{children}</div>
      <nav className="bottom-nav" aria-label="Primary navigation">
        {items.map(({ id, label, Icon, path }) => (
          <button
            key={id}
            type="button"
            className={active === id ? "active" : ""}
            aria-current={active === id ? "page" : undefined}
            onClick={() => { void navigate(path); }}
          >
            <Icon size={20} /><span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
