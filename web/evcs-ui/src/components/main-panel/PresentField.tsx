import { useEffect, useState } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import { clampPresent } from '../../utils/validation';

interface Props {
  portId: number;
  value: number;
}

export function PresentField({ portId, value }: Props) {
  const update = useEvcsStore((s) => s.updateCarPort);
  const [draft, setDraft] = useState(String(value));

  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  const commit = () => {
    const num = parseInt(draft, 10);
    // F14.3a req #2: Present must be ≥ 1 when entered. NaN or <1 → revert.
    // (Default value 0 is allowed when never edited; this guard rejects the
    // *act of entering* 0, not the persisted-default 0.)
    if (Number.isNaN(num) || num < 1) {
      setDraft(String(value));
      return;
    }
    const clamped = clampPresent(num);
    if (clamped === value) {
      setDraft(String(clamped));
      return;
    }
    update(portId, { present: clamped });
  };

  return (
    <div className="flex items-center justify-center gap-1">
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        }}
        className="w-16 text-right border border-slate-300 rounded px-2 py-1 text-sm font-mono bg-white"
        aria-label={`Car ${portId} Present (minimum 1 kW)`}
        title="Present must be ≥ 1 kW"
      />
      <span className="text-xs text-slate-600">kW</span>
    </div>
  );
}
