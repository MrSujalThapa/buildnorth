import { useState } from "react";
import { Blocks, Code2, type LucideIcon } from "lucide-react";

type Props = {
  id: string;
  logoUrl?: string;
  Icon: LucideIcon;
  size?: number;
  className?: string;
};

export function PluginBrandIcon({ id, logoUrl, Icon, size = 22, className }: Props) {
  const [broken, setBroken] = useState(false);
  if (logoUrl && !broken) {
    return (
      <img
        className={className ?? "plugin-brand-icon"}
        src={logoUrl}
        alt=""
        width={size}
        height={size}
        loading="lazy"
        decoding="async"
        data-provider={id}
        onError={() => setBroken(true)}
      />
    );
  }
  const Fallback = Icon === Code2 && id !== "github" ? Blocks : Icon;
  return <Fallback size={size} aria-hidden className={className} />;
}

export const fallbackPluginIcon = Blocks;
