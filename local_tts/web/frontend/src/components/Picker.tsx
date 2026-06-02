// Generic select-with-status-hint. Used by STT, voice, LLM model, and
// (Phase 5) persona pickers. The legacy app.js had three near-identical
// copies of populate*/setStatus/request*Swap/handle*Event — this single
// component replaces all of them. The "ready → clear hint" auto-fade is
// owned by App.tsx (where the WS event lands), so this component is a pure
// view.

import { useId } from "react";
import { SwapState } from "../state/store";

export interface PickerOption {
  value: string;
  label: string;
  // Optional <optgroup> heading. Options sharing a group are rendered together
  // under it; ungrouped options render before any groups (used to set off
  // cloned voices from presets in the voice picker).
  group?: string;
}

interface PickerProps {
  label: string;
  options: PickerOption[];
  value: string | null;
  onChange: (next: string) => void;
  status?: { text: string; kind: SwapState };
  disabled?: boolean;
}

export function Picker({
  label,
  options,
  value,
  onChange,
  status,
  disabled,
}: PickerProps) {
  const id = useId();
  const ungrouped = options.filter((o) => !o.group);
  const groups = options.reduce<Record<string, PickerOption[]>>((acc, o) => {
    if (o.group) (acc[o.group] ||= []).push(o);
    return acc;
  }, {});
  return (
    <div className="settings-row">
      <label htmlFor={id}>
        {label}
        {status?.text ? (
          <span className={`settings-hint ${status.kind || ""}`}>
            {status.text}
          </span>
        ) : null}
      </label>
      <select
        id={id}
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {ungrouped.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        {Object.entries(groups).map(([name, opts]) => (
          <optgroup key={name} label={name}>
            {opts.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
