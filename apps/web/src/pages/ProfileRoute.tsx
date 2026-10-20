import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ExecutionProfileRadar } from "../components/behavior/ExecutionProfileRadar";
import { api } from "../api/client";

const AVATARS = ["S", "J", "P", "★", "◆", "◎"];

export function ProfileRoute() {
  const queryClient = useQueryClient();
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: ({ signal }) => api.profile(signal),
  });
  const [editing, setEditing] = useState(false);
  const save = useMutation({
    mutationFn: (body: { display_name?: string; username?: string; bio?: string; avatar_value?: string }) =>
      api.patchProfile(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["profile"] });
      setEditing(false);
    },
  });

  if (profile.isLoading) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <p role="status">Loading profile…</p>
        </section>
      </main>
    );
  }

  if (profile.isError || !profile.data) {
    return (
      <main className="markets-page">
        <section className="markets-shell">
          <div className="unpriced-state">
            <strong>Profile unavailable</strong>
            <span>Could not load GET /api/v1/profile.</span>
          </div>
        </section>
      </main>
    );
  }

  const account = profile.data.account;
  const fields = account.profile ?? { display_name: null, username: null, bio: null, avatar_value: null };
  const handle = fields.username || account.email?.split("@")[0] || "you";

  return (
    <main className="markets-page profile-page">
      <section className="markets-shell">
        <header className="markets-header">
          <div className="markets-eyebrow">PROFILE</div>
          <h1>{fields.display_name || handle}</h1>
          <p>Private to your account. This is not your Clerk identity or goal ownership record.</p>
        </header>
        <section className="profile-card">
          <div className="profile-avatar" aria-hidden="true">{fields.avatar_value || handle.slice(0, 1).toUpperCase()}</div>
          <div>
            <strong>@{handle}</strong>
            <p>{fields.bio || "Add a short bio to describe how you use PlayItOut."}</p>
            <p className="field-hint">
              {profile.data.goal_count} goals · {profile.data.collection_count} collections · {profile.data.privacy}
            </p>
          </div>
          <button type="button" className="secondary" onClick={() => setEditing((value) => !value)}>
            {editing ? "Close" : "Edit"}
          </button>
        </section>
        {editing ? (
          <form
            className="composer-form"
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const text = (name: string) => {
                const value = form.get(name);
                return typeof value === "string" ? value : "";
              };
              save.mutate({
                display_name: text("display_name"),
                username: text("username"),
                bio: text("bio"),
                avatar_value: text("avatar_value") || fields.avatar_value || "",
              });
            }}
          >
            <label htmlFor="display_name">Display name</label>
            <input id="display_name" name="display_name" defaultValue={fields.display_name ?? ""} maxLength={80} />
            <label htmlFor="username">Username</label>
            <input id="username" name="username" defaultValue={fields.username ?? ""} maxLength={24} />
            <label htmlFor="bio">Bio</label>
            <textarea id="bio" name="bio" rows={3} defaultValue={fields.bio ?? ""} maxLength={280} />
            <fieldset className="avatar-picker">
              <legend>Avatar</legend>
              {AVATARS.map((item) => (
                <label key={item}>
                  <input type="radio" name="avatar_value" value={item} defaultChecked={fields.avatar_value === item} />
                  <span>{item}</span>
                </label>
              ))}
            </fieldset>
            <button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save profile"}</button>
            {save.isError ? <p className="field-hint">{String(save.error)}</p> : null}
          </form>
        ) : null}
        <ExecutionProfileRadar profile={profile.data.radar} />
      </section>
    </main>
  );
}
