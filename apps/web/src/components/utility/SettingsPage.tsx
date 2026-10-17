import { Moon, ShieldCheck, Sun } from "lucide-react";
import "./utility-pages.css";

type Props = {
  theme: "light" | "dark";
  onSetTheme: (theme: "light" | "dark") => void;
};

export default function SettingsPage({ theme, onSetTheme }: Props) {
  return (
    <main className="utility-page">
      <section className="utility-shell">
        <header className="utility-header">
          <h1>Settings</h1>
          <p>Control how Play It Out looks, connects data, and uses evidence.</p>
        </header>

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
