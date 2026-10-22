import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { ChartNoAxesCombined, Menu, Moon, Plug, Settings, Sun, Users } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
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
  const [pinned, setPinned] = useState(false);
  const photo = useQuery({
    queryKey: ["profile-photo"],
    queryFn: ({ signal }) => api.profilePhoto(signal),
    enabled: Boolean(account),
    staleTime: 5 * 60_000,
  });
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!photo.data) { setPhotoUrl(null); return; }
    const url = URL.createObjectURL(photo.data);
    setPhotoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [photo.data]);
  const profileLabel =
    account?.profile?.username || account?.profile?.display_name || account?.email?.split("@")[0] || "Profile";
  const initial = profileLabel.slice(0, 1).toUpperCase();

  return (
    <div className={`app-shell theme-${theme}`}>
      <a className="skip-link" href="#app-main">Skip to main content</a>
      <aside className={pinned ? "app-sidebar pinned" : "app-sidebar"}>
        <button className="sidebar-expand" type="button" aria-expanded={pinned} aria-label={pinned ? "Collapse navigation" : "Expand navigation"} onClick={() => setPinned((open) => !open)}>
          <Menu size={18} />
        </button>
        <button className="brand" type="button" onClick={() => { void navigate("/markets"); }} aria-label="Play It Out, go to Market">
          <b>PIO</b><span>Play It Out</span>
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
              <Icon size={20} strokeWidth={1.7} /><span className="nav-label">{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button type="button" onClick={toggle} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}>
            {theme === "light" ? <Moon size={20} /> : <Sun size={20} />}<span className="nav-label">Theme</span>
          </button>
          <button type="button" onClick={() => { void navigate("/profile"); }} aria-label="Open profile" aria-current={active === "profile" ? "page" : undefined}>
            <span className="sidebar-avatar" aria-hidden="true">{photoUrl ? <img src={photoUrl} alt="" /> : initial}</span>
            <span className="nav-label">{profileLabel}</span>
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
