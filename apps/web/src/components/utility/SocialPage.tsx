import { Lock, UsersRound } from "lucide-react";
import "./utility-pages.css";

export default function SocialPage() {
  return (
    <main className="utility-page">
      <section className="utility-shell social-shell">
        <header className="utility-header social-header">
          <div>
            <h1>Social</h1>
            <p>Follow the goals people choose to share. Your markets stay private by default.</p>
          </div>
          <div className="private-pill"><Lock size={13} /> Private by default</div>
        </header>

        <section className="social-focus">
          <div className="social-focus-copy">
            <span>YOUR CIRCLE</span>
            <h2>Progress without the performance theater.</h2>
            <p>See meaningful changes people intentionally share, not an endless activity feed.</p>
          </div>
          <UsersRound size={42} strokeWidth={1.4} />
        </section>

        <div className="social-list" role="status">
          <h2>No shared goals</h2>
          <p>Social sharing is not available yet. Your goals stay private.</p>
        </div>
      </section>
    </main>
  );
}
