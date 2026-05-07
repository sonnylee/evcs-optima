// Sprint 1: not currently mounted — ConfigPanel uses ReadOnlyField placeholders.
// Sprint 2 (FR-11): re-mount this for dynamic per-REC-BD module power lists.
import { useEffect, useState } from 'react';
import { evcsApi } from '../../api/evcsApiClient';
import { useDebounce } from '../../hooks/useDebounce';
import type { ModulePowerStringResponse } from '../../types/evcs';

interface Props {
  recBdId: number;
  initialRaw: string;
  onParsed: (recBdId: number, parsed: ModulePowerStringResponse) => void;
}

export function ModulePowerInput({ recBdId, initialRaw, onParsed }: Props) {
  const [raw, setRaw] = useState(initialRaw);
  const debounced = useDebounce(raw, 400);
  const [result, setResult] = useState<ModulePowerStringResponse | null>(null);

  useEffect(() => {
    setRaw(initialRaw);
  }, [initialRaw]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { data, error } = await evcsApi.validateModulePowers(debounced);
      if (cancelled || error || !data) return;
      setResult(data);
      onParsed(recBdId, data);
    })();
    return () => {
      cancelled = true;
    };
  }, [debounced, recBdId, onParsed]);

  const hasErrors = result?.errors && result.errors.length > 0;

  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-slate-700">
        REC BD {recBdId} module powers
      </label>
      <input
        type="text"
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder="50, 75, 75, 50"
        className={`w-full px-2 py-1 text-sm rounded border ${
          hasErrors ? 'border-red-500 ring-1 ring-red-300' : 'border-slate-300'
        }`}
      />
      {result && !hasErrors && (
        <span className="text-[10px] text-slate-500">
          {result.powers.length} modules • total {result.total_capacity_kw} kW •{' '}
          {result.pack_count} packs
        </span>
      )}
      {hasErrors && (
        <ul className="text-[10px] text-red-600 list-disc pl-4">
          {result!.errors.map((e, i) => (
            <li key={i}>{e.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
