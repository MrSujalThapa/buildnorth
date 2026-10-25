import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ParameterEditor } from "../components/behavior/ParameterEditor";
import { ParameterRadar } from "../components/behavior/ParameterRadar";
import { api } from "../api/client";
import { useRefreshAccount } from "../auth/AuthGate";
import ContributionHeatmap from "../components/social/ContributionHeatmap";
import MarketRepoList from "../components/social/MarketRepoList";
import "../components/social/social.css";
import { saveProfileWithPhoto } from "./profileSave";

async function cropPhoto(file: File, x: number, y: number): Promise<File> {
  const image = await createImageBitmap(file);
  try {
    const side = Math.min(image.width, image.height);
    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 512;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Photo preview unavailable");
    context.fillStyle = "#f8f6f1";
    context.fillRect(0, 0, 512, 512);
    context.drawImage(
      image,
      (image.width - side) * x / 100,
      (image.height - side) * y / 100,
      side, side, 0, 0, 512, 512,
    );
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
      (result) => result ? resolve(result) : reject(new Error("Could not prepare photo")),
      "image/webp", 0.84,
    ));
    return new File([blob], "profile.webp", { type: "image/webp" });
  } finally {
    image.close();
  }
}

export function ProfileRoute() {
  const queryClient = useQueryClient();
  const refreshAccount = useRefreshAccount();
  const profile = useQuery({ queryKey: ["profile"], queryFn: ({ signal }) => api.profile(signal) });
  const photo = useQuery({ queryKey: ["profile-photo"], queryFn: ({ signal }) => api.profilePhoto(signal), staleTime: 5 * 60_000 });
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [selectedPhoto, setSelectedPhoto] = useState<File | null>(null);
  const [photoPosition, setPhotoPosition] = useState({ x: 50, y: 50 });
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [pendingRemove, setPendingRemove] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [editingParameters, setEditingParameters] = useState(false);
  const [tab, setTab] = useState<"overview" | "markets" | "stars">("overview");
  const [marketQuery, setMarketQuery] = useState("");
  const [visibility, setVisibility] = useState<"all" | "public" | "private">("all");
  useEffect(() => {
    if (!photo.data) { setPhotoUrl(null); return; }
    const url = URL.createObjectURL(photo.data);
    setPhotoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [photo.data]);
  useEffect(() => {
    if (!selectedPhoto) { setPreviewUrl(null); return; }
    const url = URL.createObjectURL(selectedPhoto);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [selectedPhoto]);
  const save = useMutation({
    mutationFn: (body: { display_name: string; username: string; bio: string }) => api.patchProfile(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["profile"] });
    },
  });
  const saveParameters = useMutation({
    mutationFn: (body: { parameter_ids: string[] }) => api.patchProfile(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["profile"] });
      setEditingParameters(false);
    },
  });
  const upload = useMutation({
    mutationFn: async (file: File) => api.uploadProfilePhoto(await cropPhoto(file, photoPosition.x, photoPosition.y)),
    onSuccess: () => { setPhotoError(null); setSelectedPhoto(null); void queryClient.invalidateQueries({ queryKey: ["profile-photo"] }); },
  });
  const remove = useMutation({
    mutationFn: () => api.removeProfilePhoto(),
    onSuccess: () => { setSelectedPhoto(null); void queryClient.invalidateQueries({ queryKey: ["profile-photo"] }); },
  });
  const account = profile.data?.account;
  const fields = account?.profile ?? { display_name: null, username: null, bio: null, avatar_value: null, dimensions: [] };
  const handle = fields.username || account?.user_id || account?.email?.split("@")[0] || "you";
  const display = fields.display_name || handle;
  const socialProfile = useQuery({
    queryKey: ["public-profile", handle],
    queryFn: ({ signal }) => api.publicProfile(handle, signal),
    enabled: Boolean(profile.data && handle),
  });
  const ownMarkets = useQuery({
    queryKey: ["own-profile-markets", handle, marketQuery, visibility],
    queryFn: ({ signal }) => api.publicProfileMarkets(handle, {
      q: marketQuery || undefined,
      visibility: visibility === "all" ? undefined : visibility,
    }, signal),
    enabled: Boolean(profile.data && handle) && tab !== "stars",
  });
  const ownStars = useQuery({
    queryKey: ["own-profile-stars", handle],
    queryFn: ({ signal }) => api.publicProfileStars(handle, signal),
    enabled: Boolean(profile.data && handle) && tab === "stars",
  });

  if (profile.isLoading) return <main className="markets-page"><section className="markets-shell"><p role="status">Loading profile…</p></section></main>;
  if (profile.isError || !profile.data || !account) return <main className="markets-page"><section className="markets-shell"><p role="alert">Profile unavailable.</p></section></main>;

  const shownPhoto = pendingRemove ? null : previewUrl || photoUrl;

  function choosePhoto(file: File | undefined) {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { setPhotoError("Choose a photo under 2 MB."); return; }
    setPhotoError(null);
    setPhotoPosition({ x: 50, y: 50 });
    setSelectedPhoto(file);
  }

  return (
    <main className="markets-page profile-page">
      <section className="markets-shell">
        <h1 className="profile-page-title">Profile</h1>
        <section className="profile-card">
          <div className="profile-avatar" aria-label={shownPhoto && !editing ? "Profile photo" : "Initials avatar"}>
            {shownPhoto && !editing ? <img src={shownPhoto} alt="" width={96} height={96} /> : display.slice(0, 1).toUpperCase()}
          </div>
          <div className="profile-identity">
            <h2>{display}</h2>
            <span>@{handle}</span>
            {fields.bio ? <p>{fields.bio}</p> : null}
          </div>
          <button type="button" className="secondary" onClick={() => setEditing(true)}>Edit</button>
        </section>
        <div className="follow-counts">
          {socialProfile.data ? (
            <>
              <Link to={`/u/${handle}`}>{socialProfile.data.follower_count} followers</Link>
              <span>{socialProfile.data.following_count} following</span>
            </>
          ) : socialProfile.isError ? <span role="alert">Follow counts unavailable</span> : <span role="status">Loading follow counts&hellip;</span>}
        </div>
        <nav className="profile-tabs" aria-label="Profile sections">
          <button type="button" className={tab === "overview" ? "is-active" : ""} onClick={() => setTab("overview")}>Overview</button>
          <button type="button" className={tab === "markets" ? "is-active" : ""} onClick={() => setTab("markets")}>Markets</button>
          <button type="button" className={tab === "stars" ? "is-active" : ""} onClick={() => setTab("stars")}>Stars</button>
        </nav>
        {tab === "overview" ? (
          <>
            <div className="profile-radar-heading">
              <h2>Your parameters</h2>
              {profile.data.radar ? (
                <button type="button" className="markets-select" onClick={() => setEditingParameters(true)}>
                  Edit parameters
                </button>
              ) : null}
            </div>
            {profile.data.radar ? (
              <ParameterRadar profile={profile.data.radar} />
            ) : (
              <p className="profile-radar-pending" role="status">Measured parameters are unavailable right now.</p>
            )}
            {socialProfile.isError ? <p role="alert">Could not load activity. <button type="button" onClick={() => void socialProfile.refetch()}>Try again</button></p> : socialProfile.isLoading ? <p role="status">Loading activity&hellip;</p> : <ContributionHeatmap
              days={socialProfile.data?.activity ?? []}
              total={socialProfile.data?.contribution_total ?? 0}
            />}
          </>
        ) : null}
        {tab === "markets" ? (
          <>
            <div className="discover-tools">
              <input className="repo-search" value={marketQuery} onChange={(event) => setMarketQuery(event.target.value)} placeholder="Find a market…" aria-label="Find a market" />
              <select value={visibility} onChange={(event) => setVisibility(event.target.value as typeof visibility)} aria-label="Filter visibility">
                <option value="all">All</option>
                <option value="public">Public</option>
                <option value="private">Private</option>
              </select>
            </div>
            {ownMarkets.isError ? <p role="alert">Could not load markets. <button type="button" onClick={() => void ownMarkets.refetch()}>Try again</button></p> : ownMarkets.isLoading ? <p role="status">Loading markets&hellip;</p> : <MarketRepoList items={ownMarkets.data?.items ?? []} empty="No markets match that filter." />}
          </>
        ) : null}
        {tab === "stars" ? (
          ownStars.isError ? <p role="alert">Could not load stars. <button type="button" onClick={() => void ownStars.refetch()}>Try again</button></p> : ownStars.isLoading ? <p role="status">Loading stars&hellip;</p> : <MarketRepoList items={ownStars.data?.items ?? []} empty="You have not starred a public market yet." />
        ) : null}
      </section>
      {editing ? <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="edit-profile-title">
        <form className="confirm-card profile-editor" onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const field = (name: string) => {
            const value = data.get(name);
            return typeof value === "string" ? value : "";
          };
          const pending = selectedPhoto;
          const shouldRemove = pendingRemove;
          const previous = {
            display_name: fields.display_name ?? "",
            username: fields.username ?? "",
            bio: fields.bio ?? "",
          };
          setSaveError(null);
          void (async () => {
            try {
              await saveProfileWithPhoto(
                { display_name: field("display_name"), username: field("username"), bio: field("bio") },
                previous,
                (details) => save.mutateAsync(details),
                shouldRemove ? () => remove.mutateAsync() : pending ? () => upload.mutateAsync(pending) : undefined,
              );
              await refreshAccount().catch(() => undefined);
              setPendingRemove(false);
              setSelectedPhoto(null);
              setEditing(false);
            } catch (error) {
              await refreshAccount().catch(() => undefined);
              setSaveError(error instanceof Error ? error.message : "Could not save profile.");
            }
          })();
        }}>
          <h2 id="edit-profile-title">Edit profile</h2>
          <div className="profile-edit-photo">
            <div className="profile-avatar large" aria-label="Profile photo preview">
              {shownPhoto ? <img src={shownPhoto} alt="" width={112} height={112} style={previewUrl ? { objectPosition: `${photoPosition.x}% ${photoPosition.y}%` } : undefined} /> : display.slice(0, 1).toUpperCase()}
            </div>
            <div className="profile-edit-photo-actions">
              <label className="markets-select" htmlFor="profile-photo-input">{photoUrl || selectedPhoto ? "Change photo" : "Add photo"}</label>
              <input id="profile-photo-input" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => { choosePhoto(event.target.files?.[0]); event.currentTarget.value = ""; }} />
              {shownPhoto || photoUrl || selectedPhoto ? (
                <button
                  type="button"
                  className="markets-select"
                  onClick={() => {
                    setSelectedPhoto(null);
                    setPendingRemove(true);
                    setPhotoError(null);
                  }}
                >
                  Remove photo
                </button>
              ) : null}
            </div>
          </div>
          {selectedPhoto ? (
            <div className="profile-photo-position">
              <label>Horizontal position<input type="range" min="0" max="100" value={photoPosition.x} onChange={(event) => setPhotoPosition((current) => ({ ...current, x: Number(event.target.value) }))} /></label>
              <label>Vertical position<input type="range" min="0" max="100" value={photoPosition.y} onChange={(event) => setPhotoPosition((current) => ({ ...current, y: Number(event.target.value) }))} /></label>
            </div>
          ) : null}
          {upload.isPending ? <span role="status">Uploading…</span> : null}
          {photoError || upload.isError || remove.isError ? <span role="alert">{photoError || "Photo could not be saved. Choose a JPEG, PNG or WebP image."}</span> : null}
          <label htmlFor="display_name">Display name</label>
          <input id="display_name" name="display_name" className="ui-field" autoComplete="name" defaultValue={fields.display_name ?? ""} maxLength={80} />
          <label htmlFor="username">Username</label>
          <input id="username" name="username" className="ui-field" autoComplete="username" spellCheck={false} defaultValue={fields.username ?? ""} maxLength={24} />
          <label htmlFor="bio">Bio</label>
          <textarea id="bio" name="bio" className="ui-field" rows={3} defaultValue={fields.bio ?? ""} maxLength={280} />
          {save.isError || saveError ? <p role="alert">{saveError || "Could not save profile. Check the username and try again."}</p> : null}
          <div className="composer-actions">
            <button type="submit" className="ui-button" disabled={save.isPending || upload.isPending || remove.isPending}>
              {save.isPending || upload.isPending || remove.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              className="secondary ui-button ui-button-secondary"
              onClick={() => {
                setEditing(false);
                setSelectedPhoto(null);
                setPendingRemove(false);
                setSaveError(null);
                setPhotoError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      </div> : null}
      {editingParameters ? (
        <ParameterEditor
          selected={profile.data.selected_parameters}
          options={profile.data.available_parameters}
          saving={saveParameters.isPending}
          error={saveParameters.isError ? "Could not save parameters." : null}
          onSave={(payload) => saveParameters.mutate(payload)}
          onCancel={() => { saveParameters.reset(); setEditingParameters(false); }}
        />
      ) : null}
    </main>
  );
}
