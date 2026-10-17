import { GitBranch, Repeat2, Route, Columns2, type LucideIcon } from "lucide-react";
import type { WhatIfMode } from "../../adapters/templateTypes";

type Props = {
  mode: WhatIfMode;
  onChange: (mode: WhatIfMode) => void;
};

const modes: Array<{
  id: WhatIfMode;
  label: string;
  description: string;
  icon: LucideIcon;
}> = [
  {
    id: "impact",
    label: "Change",
    description: "See how one action changes your odds.",
    icon: Repeat2,
  },
  {
    id: "futures",
    label: "Futures",
    description: "See the main ways this could play out.",
    icon: GitBranch,
  },
  {
    id: "compare",
    label: "Compare",
    description: "See how your selected options differ.",
    icon: Columns2,
  },
  {
    id: "paths",
    label: "Paths",
    description: "Find realistic strategies that could get you there.",
    icon: Route,
  },
];

export default function WhatIfModeNav({ mode, onChange }: Props) {
  return (
    <nav className="what-if-mode-nav" aria-label="What If mode">
      <div className="mode-nav-track" role="tablist">
        {modes.map((item) => {
          const selected = item.id === mode;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={selected}
              className={selected ? "mode-nav-item selected" : "mode-nav-item"}
              onClick={() => onChange(item.id)}
            >
              <Icon size={17} strokeWidth={1.7} aria-hidden="true" />
              <strong>{item.label}</strong>
            </button>
          );
        })}
      </div>
      <p className="mode-nav-description"><strong>{modes.find((item) => item.id === mode)?.label}</strong> {modes.find((item) => item.id === mode)?.description}</p>
    </nav>
  );
}
