"use client";

import { Card, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group";

export const COPILOT_APPLY_MODES = [
  {
    id: "easyApplyLocal",
    label: "Easy Apply (Local)",
    enabled: true,
  },
  {
    id: "easyApplyRemote",
    label: "Easy Apply (Remote)",
    enabled: true,
  },
  {
    id: "companyApplyLocal",
    label: "Company Apply (Local)",
    enabled: false,
  },
  {
    id: "companyApplyRemote",
    label: "Company Apply (Remote)",
    enabled: false,
  },
];

/**
 * Copilot run mode picker — maps to agent.json searchUrls slots.
 */
export default function CopilotSettings({
  applyMode = "easyApplyLocal",
  onApplyModeChange,
  disabled = false,
}) {
  function handleChange(groupValue) {
    const next = Array.isArray(groupValue) ? groupValue[0] : groupValue;
    if (!next) return;
    const meta = COPILOT_APPLY_MODES.find((m) => m.id === next);
    if (!meta?.enabled) return;
    onApplyModeChange?.(next);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Apply mode</CardTitle>
      </CardHeader>
      <CardPanel className="space-y-3">
        <ToggleGroup
          variant="outline"
          value={[applyMode]}
          onValueChange={handleChange}
          disabled={disabled}
          className="flex flex-wrap gap-1.5"
          aria-label="Copilot apply mode"
        >
          {COPILOT_APPLY_MODES.map((mode) => (
            <ToggleGroupItem
              key={mode.id}
              value={mode.id}
              disabled={disabled || !mode.enabled}
              aria-label={mode.label}
              title={mode.enabled ? mode.label : `${mode.label} — Coming soon`}
            >
              {mode.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <p className="m-0 text-xs text-muted-foreground">
          Easy Apply uses your Glassdoor filtered URLs from{" "}
          <code className="text-[0.7rem]">config/agent.json</code>. Company Apply
          is coming soon.
        </p>
      </CardPanel>
    </Card>
  );
}

export function applyModeShortLabel(modeId) {
  const meta = COPILOT_APPLY_MODES.find((m) => m.id === modeId);
  if (!meta) return modeId || "—";
  if (modeId === "easyApplyLocal") return "Easy Apply · Local";
  if (modeId === "easyApplyRemote") return "Easy Apply · Remote";
  if (modeId === "companyApplyLocal") return "Company Apply · Local";
  if (modeId === "companyApplyRemote") return "Company Apply · Remote";
  return meta.label;
}
