import { useEffect, useState } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import { clampOnly } from '../../utils/validation';

interface Props {
  portId: number;
  value: number;
}

export function MaxRequiredField({ portId, value }: Props) {
  const update = useEvcsStore((s) => s.updateCarPort);
  const [draft, setDraft] = useState(String(value));

  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  // TODO(F09.6 §1.3 / Sprint 2): potential race condition — if user types
  // again before the async update settles, the next useEffect may
  // overwrite the new draft with the previous value. Not reproducible
  // in normal demo flow (user can't type fast enough), but should be
  // hardened in Sprint 2 with an in-flight request token check.
  const commit = () => {
    const num = parseInt(draft, 10);
    if (Number.isNaN(num)) {
      setDraft(String(value));
      return;
    }
    const clamped = clampOnly(num);
    if (clamped === value) {
      setDraft(String(clamped));
      return;
    }
    update(portId, { max_required: clamped });
  };

  return (
    <input
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
      }}
      className="w-16 text-right border border-slate-300 rounded px-2 py-1 text-sm font-mono"
      aria-label={`Car ${portId} Max Required`}
    />
  );
}
