import { Globe, Lock } from "lucide-react";

type Visibility = "public" | "private";

type Props = {
  visibility: Visibility;
  onToggle: () => void;
  disabled?: boolean;
};

function VisibilityIcon({ visibility }: { visibility: Visibility }) {
  return visibility === "private"
    ? <Lock size={12} strokeWidth={2.2} aria-hidden="true" />
    : <Globe size={12} strokeWidth={2.2} aria-hidden="true" />;
}

export function VisibilityBadge({ visibility }: { visibility: Visibility }) {
  return (
    <span className={`visibility-badge is-${visibility}`}>
      <VisibilityIcon visibility={visibility} />
      <span>{visibility === "private" ? "Private" : "Public"}</span>
    </span>
  );
}

export default function VisibilityControl({ visibility, onToggle, disabled }: Props) {
  const isPrivate = visibility === "private";
  return (
    <button
      type="button"
      className={`visibility-control is-${visibility}`}
      onClick={onToggle}
      disabled={disabled}
      aria-label={`${isPrivate ? "Private" : "Public"} market. ${isPrivate ? "Make public" : "Make private"}`}
      title={isPrivate ? "Only you can see this market. Click to publish." : "Anyone with the link can see this market. Click to make private."}
    >
      <VisibilityIcon visibility={visibility} />
      <span>{isPrivate ? "Private" : "Public"}</span>
    </button>
  );
}
