import { Lock, Unlock } from "lucide-react";

type Props = {
  visibility: "public" | "private";
  onToggle: () => void;
  disabled?: boolean;
};

export default function VisibilityControl({ visibility, onToggle, disabled }: Props) {
  const isPrivate = visibility === "private";
  return (
    <button
      type="button"
      className={`visibility-control is-${visibility}`}
      onClick={onToggle}
      disabled={disabled}
      aria-label={`${isPrivate ? "Private" : "Public"} market. Change visibility`}
    >
      {isPrivate ? <Lock size={14} strokeWidth={2} /> : <Unlock size={14} strokeWidth={2} />}
      <span>{isPrivate ? "Private" : "Public"}</span>
    </button>
  );
}
