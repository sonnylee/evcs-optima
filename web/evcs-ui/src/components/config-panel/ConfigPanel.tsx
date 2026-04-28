import { useCallback, useMemo, useState } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import type { ModulePowerStringResponse, SystemConfig } from '../../types/evcs';
import { Button } from '../shared/Button';
import { ErrorBanner } from '../shared/ErrorBanner';
import { ModulePowerInput } from './ModulePowerInput';
import { RecBdCountInput } from './RecBdCountInput';

const DEFAULT_RAW = '50, 75, 75, 50';

function ensureLength(arr: string[], n: number, fill: string): string[] {
  if (arr.length === n) return arr;
  if (arr.length > n) return arr.slice(0, n);
  return [...arr, ...Array(n - arr.length).fill(fill)];
}

export function ConfigPanel() {
  const systemConfig = useEvcsStore((s) => s.systemConfig);
  const configErrors = useEvcsStore((s) => s.configErrors);
  const isLoading = useEvcsStore((s) => s.isLoading);
  const updateSystemConfig = useEvcsStore((s) => s.updateSystemConfig);
  const clearConfigErrors = useEvcsStore((s) => s.clearConfigErrors);

  const initialCount = systemConfig?.rec_bd_count ?? 4;
  const initialRaws = useMemo(
    () =>
      systemConfig?.rec_bds.map((b) => b.module_powers.join(', ')) ??
      Array(initialCount).fill(DEFAULT_RAW),
    [systemConfig, initialCount],
  );

  const [recBdCount, setRecBdCount] = useState(initialCount);
  const [moduleStrings, setModuleStrings] = useState<string[]>(initialRaws);
  const [parsed, setParsed] = useState<Record<number, ModulePowerStringResponse>>({});
  const [showPriorityClearWarning, setShowPriorityClearWarning] = useState(false);

  const onCountChange = (n: number) => {
    if (systemConfig && n !== systemConfig.rec_bd_count) {
      setShowPriorityClearWarning(true);
    }
    setRecBdCount(n);
    setModuleStrings((prev) => ensureLength(prev, n, DEFAULT_RAW));
  };

  const onParsed = useCallback(
    (recBdId: number, r: ModulePowerStringResponse) => {
      setParsed((prev) => ({ ...prev, [recBdId]: r }));
    },
    [],
  );

  const allParsedClean =
    moduleStrings.every((_, i) => {
      const r = parsed[i + 1];
      return r && r.errors.length === 0 && r.powers.length > 0;
    });

  const canApply = allParsedClean && !isLoading;

  const onApply = async () => {
    setShowPriorityClearWarning(false);
    const cfg: SystemConfig = {
      rec_bd_count: recBdCount,
      rec_bds: moduleStrings.slice(0, recBdCount).map((_, i) => ({
        id: i + 1,
        module_powers: parsed[i + 1]?.powers ?? [],
      })),
    };
    await updateSystemConfig(cfg);
  };

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-bold text-slate-800">Configuration (FR-10 / FR-11)</h2>

      <ErrorBanner errors={configErrors} onDismiss={clearConfigErrors} />

      <RecBdCountInput value={recBdCount} onChange={onCountChange} />

      {showPriorityClearWarning && (
        <div className="rounded border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-900">
          REC BD count change will clear all Car Port priority assignments (FR-16).
        </div>
      )}

      <div className="flex flex-col gap-2">
        {Array.from({ length: recBdCount }, (_, i) => (
          <ModulePowerInput
            key={i + 1}
            recBdId={i + 1}
            initialRaw={moduleStrings[i] ?? DEFAULT_RAW}
            onParsed={onParsed}
          />
        ))}
      </div>

      <div className="pt-1">
        <Button onClick={onApply} disabled={!canApply}>
          {isLoading ? 'Applying…' : 'Apply'}
        </Button>
      </div>
    </section>
  );
}
