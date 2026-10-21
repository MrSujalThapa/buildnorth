import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ExecutionProfileRadar } from "../components/behavior/ExecutionProfileRadar";
import { api } from "../api/client";

function moved<T>(items: T[], from: number, to: number): T[] {
  const next = [...items];
  if (to < 0 || to >= next.length) return next;
  const [item] = next.splice(from, 1);
  if (item !== undefined) next.splice(to, 0, item);
  return next;
}

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
  const profile = useQuery({ queryKey: ["profile"], queryFn: ({ signal }) => api.profile(signal) });
  const photo = useQuery({ queryKey: ["profile-photo"], queryFn: ({ signal }) => api.profilePhoto(signal) });
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [selectedPhoto, setSelectedPhoto] = useState<File | null>(null);
  const [photoPosition, setPhotoPosition] = useState({ x: 50, y: 50 });
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editingDimensions, setEditingDimensions] = useState(false);
  const [selectedArea, setSelectedArea] = useState("Overall");
  const [dimensions, setDimensions] = useState<{ label: string; goal_ids: string[] }[]>([]);
  const goals = useQuery({ queryKey: ["goals", "list"], queryFn: ({ signal }) => api.goals(signal), enabled: editingDimensions });
  const [photoError, setPhotoError] = useState<string | null>(null);
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
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["profile"] }); setEditing(false); },
  });
  const saveDimensions = useMutation({
    mutationFn: () => api.patchProfile({ dimensions: dimensions.filter((item) => item.label.trim()).map((item) => ({ ...item, label: item.label.trim() })) }),
    onSuccess: () => { setEditingDimensions(false); void queryClient.invalidateQueries({ queryKey: ["profile"] }); },
  });
  const upload = useMutation({
    mutationFn: async (file: File) => api.uploadProfilePhoto(await cropPhoto(file, photoPosition.x, photoPosition.y)),
    onSuccess: () => { setPhotoError(null); setSelectedPhoto(null); void queryClient.invalidateQueries({ queryKey: ["profile-photo"] }); },
  });
  const remove = useMutation({
    mutationFn: () => api.removeProfilePhoto(),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["profile-photo"] }); },
  });

  if (profile.isLoading) return <main className="markets-page"><section className="markets-shell"><p role="status">Loading profile…</p></section></main>;
  if (profile.isError || !profile.data) return <main className="markets-page"><section className="markets-shell"><p role="alert">Profile unavailable.</p></section></main>;

  const account = profile.data.account;
  const fields = account.profile ?? { display_name: null, username: null, bio: null, avatar_value: null, dimensions: [] };
  const handle = fields.username || account.email?.split("@")[0] || "you";
  const display = fields.display_name || handle;
  return (
    <main className="markets-page profile-page">
      <section className="markets-shell">
        <header className="markets-header"><h1>Profile</h1></header>
        <section className="profile-card">
          <div className="profile-avatar" aria-label={previewUrl || photoUrl ? "Profile photo preview" : "Initials avatar"}>
            {previewUrl || photoUrl ? <img src={previewUrl || photoUrl || ""} alt="" width={96} height={96} style={previewUrl ? { objectPosition: `${photoPosition.x}% ${photoPosition.y}%` } : undefined} /> : display.slice(0, 1).toUpperCase()}
          </div>
          <div className="profile-identity"><strong>{display}</strong><span>@{handle}</span>{fields.bio ? <p>{fields.bio}</p> : null}</div>
          <button type="button" className="secondary" onClick={() => setEditing(true)}>Edit</button>
        </section>
        <div className="profile-photo-actions">
          <label className="markets-select" htmlFor="profile-photo-input">{photoUrl ? "Replace photo" : "Add photo"}</label>
          <input id="profile-photo-input" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (file.size > 2 * 1024 * 1024) { setPhotoError("Choose a photo under 2 MB."); return; }
            setPhotoError(null);
            setPhotoPosition({ x: 50, y: 50 });
            setSelectedPhoto(file);
            event.currentTarget.value = "";
          }} />
          {selectedPhoto ? <>
            <div className="profile-photo-position">
              <label>Horizontal position<input type="range" min="0" max="100" value={photoPosition.x} onChange={(event) => setPhotoPosition((current) => ({ ...current, x: Number(event.target.value) }))} /></label>
              <label>Vertical position<input type="range" min="0" max="100" value={photoPosition.y} onChange={(event) => setPhotoPosition((current) => ({ ...current, y: Number(event.target.value) }))} /></label>
            </div>
            <button type="button" className="markets-select" disabled={upload.isPending} onClick={() => upload.mutate(selectedPhoto)}>Save photo</button>
            <button type="button" className="markets-select" onClick={() => setSelectedPhoto(null)}>Cancel</button>
          </> : null}
          {photoUrl && !selectedPhoto ? <button type="button" className="markets-select" disabled={remove.isPending} onClick={() => remove.mutate()}>Remove photo</button> : null}
          {upload.isPending ? <span role="status">Uploading…</span> : null}
          {photoError || upload.isError || remove.isError ? <span role="alert">{photoError || "Photo could not be saved. Choose a JPEG, PNG or WebP image."}</span> : null}
        </div>
        <div className="profile-radar-heading"><h2>Execution profile</h2><button type="button" className="markets-select" onClick={() => { setDimensions(fields.dimensions ?? []); setEditingDimensions(true); }}>Edit areas</button></div>
        <div className="profile-area-filter" role="group" aria-label="Execution area">
          <button type="button" aria-pressed={selectedArea === "Overall"} onClick={() => setSelectedArea("Overall")}>Overall</button>
          {profile.data.radar_areas?.map((area) => <button type="button" key={area.label} aria-pressed={selectedArea === area.label} onClick={() => setSelectedArea(area.label)}>{area.label}</button>)}
        </div>
        <ExecutionProfileRadar profile={profile.data.radar_areas?.find((area) => area.label === selectedArea)?.radar ?? profile.data.radar} />
      </section>
      {editing ? <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="edit-profile-title">
        <form className="confirm-card profile-editor" onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const field = (name: string) => {
            const value = data.get(name);
            return typeof value === "string" ? value : "";
          };
          save.mutate({ display_name: field("display_name"), username: field("username"), bio: field("bio") });
        }}>
          <h2 id="edit-profile-title">Edit profile</h2>
          <label htmlFor="display_name">Display name</label><input id="display_name" name="display_name" className="ui-field" autoComplete="name" defaultValue={fields.display_name ?? ""} maxLength={80} />
          <label htmlFor="username">Username</label><input id="username" name="username" className="ui-field" autoComplete="username" spellCheck={false} defaultValue={fields.username ?? ""} maxLength={24} />
          <label htmlFor="bio">Bio</label><textarea id="bio" name="bio" className="ui-field" rows={3} defaultValue={fields.bio ?? ""} maxLength={280} />
          {save.isError ? <p role="alert">Could not save profile. Check the username and try again.</p> : null}
          <div className="composer-actions"><button type="submit" className="ui-button" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save"}</button><button type="button" className="secondary ui-button ui-button-secondary" onClick={() => setEditing(false)}>Cancel</button></div>
        </form>
      </div> : null}
      {editingDimensions ? <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="edit-dimensions-title">
        <div className="confirm-card profile-editor profile-dimension-editor">
          <h2 id="edit-dimensions-title">Your areas</h2>
          {dimensions.map((item, index) => <div className="profile-dimension-row" key={index}>
            <input className="ui-field" aria-label={`Area ${index + 1} name`} value={item.label} maxLength={32} onChange={(event) => setDimensions((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, label: event.target.value } : row))} />
            <div className="profile-dimension-controls"><button type="button" disabled={index === 0} onClick={() => setDimensions((current) => moved(current, index, index - 1))}>↑</button><button type="button" disabled={index === dimensions.length - 1} onClick={() => setDimensions((current) => moved(current, index, index + 1))}>↓</button><button type="button" onClick={() => setDimensions((current) => current.filter((_, rowIndex) => rowIndex !== index))}>Remove</button></div>
            <div className="profile-dimension-goals">{goals.data?.map((goal) => <label key={goal.goal_id} className="ui-choice"><input type="checkbox" checked={item.goal_ids.includes(goal.goal_id)} onChange={() => setDimensions((current) => current.map((row, rowIndex) => rowIndex === index ? { ...row, goal_ids: row.goal_ids.includes(goal.goal_id) ? row.goal_ids.filter((id) => id !== goal.goal_id) : [...row.goal_ids, goal.goal_id] } : row))} />{goal.title}</label>)}</div>
          </div>)}
          <button type="button" className="markets-select" disabled={dimensions.length >= 12} onClick={() => setDimensions((current) => [...current, { label: "", goal_ids: [] }])}>Add area</button>
          {saveDimensions.isError ? <p role="alert">Could not save areas.</p> : null}
          <div className="composer-actions"><button type="button" disabled={saveDimensions.isPending || dimensions.some((item) => !item.label.trim())} onClick={() => saveDimensions.mutate()}>Save</button><button type="button" className="secondary" onClick={() => setEditingDimensions(false)}>Cancel</button></div>
        </div>
      </div> : null}
    </main>
  );
}
