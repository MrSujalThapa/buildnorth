import { Code2, type LucideIcon } from "lucide-react";

type Props = {
  id: string;
  logoUrl?: string;
  Icon: LucideIcon;
  size?: number;
  className?: string;
};

export function PluginBrandIcon({ id, logoUrl, Icon, size = 22, className }: Props) {
  if (logoUrl) {
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
      />
    );
  }
  return <Icon size={size} aria-hidden className={className} />;
}

export const fallbackPluginIcon = Code2;
