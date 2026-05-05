import { useEffect, useState } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import { clampMaxRequired } from '../../utils/validation';

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
    if (Number.isNaN(num)) {
      setDraft(String(value));
      return;
    }
    const rounded = clampMaxRequired(num);
    if (rounded === value) {
      setDraft(String(rounded));
      return;
    }
    update(portId, { present: rounded });
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
        aria-label={`Car ${portId} Present`}
      />
      <span className="text-xs text-slate-600">kW</span>
    </div>
  );
}
