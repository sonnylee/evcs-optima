import { useEffect, useState } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import { clampPresent } from '../../utils/validation';

interface Props {
  portId: number;
  value: number;
}

const FLASH_MS = 250;

export function PresentField({ portId, value }: Props) {
  const update = useEvcsStore((s) => s.updateCarPort);
  // F14.3b: value=0 displays as empty (placeholder "—"); >0 shows verbatim.
  // This makes the "no Present set" state visually distinct from a typed 0.
  const [draft, setDraft] = useState(value === 0 ? '' : String(value));
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    setDraft(value === 0 ? '' : String(value));
  }, [value]);

  const flashError = () => {
    setFlash(true);
    window.setTimeout(() => setFlash(false), FLASH_MS);
  };

  const commit = () => {
    // Empty input — silent revert, no flash (user might just be clearing to retype).
    if (draft.trim() === '') {
      setDraft(value === 0 ? '' : String(value));
      return;
    }
    const num = parseInt(draft, 10);
    // F14.3a/F14.3b: Present must be ≥ 1. NaN, ≤0, or non-numeric → flash + revert.
    if (Number.isNaN(num) || num < 1) {
      flashError();
      setDraft(value === 0 ? '' : String(value));
      return;
    }
    const clamped = clampPresent(num);
    if (clamped === value) {
      setDraft(String(clamped));
      return;
    }
    update(portId, { present: clamped });
  };

  const borderClass = flash
    ? 'border-red-500 ring-1 ring-red-300'
    : 'border-slate-300';

  return (
    <div className="flex items-center justify-center gap-1">
      <input
        type="number"
        inputMode="numeric"
        min={1}
        max={600}
        value={draft}
        placeholder="—"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        }}
        className={`w-16 text-right border ${borderClass} rounded px-2 py-1 text-sm font-mono bg-white transition-colors`}
        aria-label={`Car ${portId} Present (minimum 1 kW; default unset)`}
        title="Present must be ≥ 1 kW"
      />
      <span className="text-xs text-slate-600">kW</span>
    </div>
  );
}
