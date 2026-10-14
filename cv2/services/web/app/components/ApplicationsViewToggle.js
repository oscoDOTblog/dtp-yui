"use client";

import {
  ToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group";

const MODES = [
  { id: "timeline", label: "Timeline" },
  { id: "calendar", label: "Calendar" },
];

export default function ApplicationsViewToggle({ value, onChange }) {
  function handleChange(groupValue) {
    const mode = Array.isArray(groupValue) ? groupValue[0] : groupValue;
    if (mode !== "timeline" && mode !== "calendar") return;
    onChange(mode);
  }

  return (
    <ToggleGroup
      variant="outline"
      value={[value]}
      onValueChange={handleChange}
      className="mb-5 flex flex-wrap gap-1.5"
      aria-label="Applications view mode"
    >
      {MODES.map((mode) => (
        <ToggleGroupItem
          key={mode.id}
          value={mode.id}
          aria-label={mode.label}
        >
          {mode.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
