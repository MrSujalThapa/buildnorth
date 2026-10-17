import { ArrowUpRight, Lock, UsersRound } from "lucide-react";
import "./utility-pages.css";

const people = [
  { name: "Maya", note: "Training for a half marathon", change: "+3.4 pts" },
  { name: "Theo", note: "Trying to ship his startup beta", change: "+5.1 pts" },
  { name: "Ari", note: "Preparing for product interviews", change: "+2.2 pts" },
];

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

        <div className="social-list">
          {people.map((person) => (
            <button className="social-row" key={person.name} type="button">
              <span className="social-avatar">{person.name[0]}</span>
              <span className="social-copy"><strong>{person.name}</strong><span>{person.note}</span></span>
              <span className="social-change">{person.change}</span>
              <ArrowUpRight size={17} />
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}
