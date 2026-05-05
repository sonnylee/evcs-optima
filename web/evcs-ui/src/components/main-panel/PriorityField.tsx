import { useEffect, useState } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';

interface Props {
  portId: number;
  value: number | null | undefined;
  allPriorities: number[];
  maxN: number;
}

export function PriorityField({ portId, value, allPriorities, maxN }: Props) {
  const update = useEvcsStore((s) => s.updateCarPort);
  const [draft, setDraft] = useState(value == null ? '' : String(value));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(value == null ? '' : String(value));
    setError(null);
  }, [value]);

  const commit = () => {
    setError(null);
    if (draft.trim() === '') {
      if (value != null) {
        update(portId, { priority: null });
      }
      return;
    }
    const num = parseInt(draft, 10);
    if (Number.isNaN(num) || num < 1 || num > maxN) {
      setError(`Range 1-${maxN}`);
      return;
    }
    if (allPriorities.includes(num)) {
      setError(`#${num} taken`);
      return;
    }
    if (num === value) return;
    update(portId, { priority: num });
  };

  return (
    <div className="flex flex-col items-center">
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        }}
        className={`w-12 text-center border rounded py-1 text-sm font-mono ${
          error ? 'border-red-500 bg-red-50' : 'border-slate-300 bg-white'
        }`}
        aria-label={`Car ${portId} priority`}
        placeholder="—"
      />
      {error && <span className="text-[10px] text-red-600 mt-0.5">{error}</span>}
    </div>
  );
}
