import { useCallback, useEffect, useMemo, useState } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import type { ModulePowerStringResponse, SystemConfig } from '../../types/evcs';
import { REC_BD_MAX, REC_BD_MIN } from '../../utils/validation';
import { ModulePowerInput } from './ModulePowerInput';
import { RecBdCountInput } from './RecBdCountInput';

const DEFAULT_MODULE_POWERS_RAW = '50, 75, 75, 50';
const DEFAULT_REC_BD_COUNT = 4;

const rawsFromConfig = (cfg: SystemConfig | null): string[] => {
  if (!cfg) {
    return Array.from({ length: DEFAULT_REC_BD_COUNT }, () => DEFAULT_MODULE_POWERS_RAW);
  }
  return cfg.rec_bds.map((b) => b.module_powers.join(', '));
};

export function ConfigPanel() {
  const systemConfig = useEvcsStore((s) => s.systemConfig);
  const isLoading = useEvcsStore((s) => s.isLoading);
  const updateSystemConfig = useEvcsStore((s) => s.updateSystemConfig);

  const [draftCount, setDraftCount] = useState<number>(
    () => systemConfig?.rec_bd_count ?? DEFAULT_REC_BD_COUNT,
  );
  const [draftRaws, setDraftRaws] = useState<string[]>(() => rawsFromConfig(systemConfig));
  const [parsedByBd, setParsedByBd] = useState<Record<number, ModulePowerStringResponse>>({});

  // Re-flow draft when the store's systemConfig reference changes (after Apply).
  // User typing is preserved because draft state isn't in the deps.
  useEffect(() => {
    if (!systemConfig) return;
    setDraftCount(systemConfig.rec_bd_count);
    setDraftRaws(rawsFromConfig(systemConfig));
  }, [systemConfig]);

  const onCountChange = (next: number) => {
    setDraftRaws((prev) => {
      if (next > prev.length) {
        return [
          ...prev,
          ...Array.from({ length: next - prev.length }, () => DEFAULT_MODULE_POWERS_RAW),
        ];
      }
      if (next < prev.length) {
        return prev.slice(0, next);
      }
      return prev;
    });
    setDraftCount(next);
  };

  // Memoized so ModulePowerInput's useEffect (which has onParsed in deps)
  // doesn't re-fire validateModulePowers every render.
  const onParsed = useCallback(
    (recBdId: number, parsed: ModulePowerStringResponse) => {
      setParsedByBd((prev) => ({ ...prev, [recBdId]: parsed }));
    },
    [],
  );

  const countInRange = draftCount >= REC_BD_MIN && draftCount <= REC_BD_MAX;
  const allParsedCleanly = useMemo(() => {
    if (!countInRange) return false;
    for (let i = 1; i <= draftCount; i++) {
      const r = parsedByBd[i];
      if (!r) return false;
      if (r.errors && r.errors.length > 0) return false;
    }
    return true;
  }, [countInRange, draftCount, parsedByBd]);

  const totalCapacityKw = useMemo(() => {
    if (!allParsedCleanly) return null;
    let sum = 0;
    for (let i = 1; i <= draftCount; i++) {
      sum += parsedByBd[i]!.total_capacity_kw;
    }
    return sum;
  }, [allParsedCleanly, draftCount, parsedByBd]);

  const totalPorts = draftCount * 2;
  const applyDisabled = isLoading || !allParsedCleanly;

  const onApply = async () => {
    if (applyDisabled) return;
    const cfg: SystemConfig = {
      rec_bd_count: draftCount,
      rec_bds: Array.from({ length: draftCount }, (_, i) => ({
        id: i + 1,
        module_powers: parsedByBd[i + 1]!.powers,
      })),
    };
    await updateSystemConfig(cfg);
  };

  return (
    <section className="flex flex-col gap-3" data-testid="config-panel">
      <div className="bg-slate-700 text-white text-center py-2 rounded-md font-semibold text-sm">
        配置 (Configuration)
      </div>

      <div className="bg-white border border-slate-200 rounded-md px-3 py-2">
        <RecBdCountInput value={draftCount} onChange={onCountChange} />
      </div>

      <div className="bg-white border border-slate-200 rounded-md px-3 py-2 flex flex-col gap-2">
        {draftRaws.map((raw, idx) => (
          <ModulePowerInput
            key={idx + 1}
            recBdId={idx + 1}
            initialRaw={raw}
            onParsed={onParsed}
          />
        ))}
      </div>

      <SummaryRow
        label="總容量"
        value={totalCapacityKw === null ? '—' : `${totalCapacityKw} kW`}
        valueClass="text-green-600"
      />

      <SummaryRow
        label="總充電槍數"
        value={String(totalPorts)}
        valueClass="text-teal-600"
      />

      <div className="bg-slate-50 border border-slate-200 rounded-md px-3 py-2 text-center">
        <div className="text-xs font-semibold text-slate-700">硬體拓撲預覽</div>
        <div className="text-[11px] text-slate-500">
          {draftCount} REC BD × 2 Outputs = {totalPorts} Cars
        </div>
      </div>

      <button
        type="button"
        onClick={onApply}
        disabled={applyDisabled}
        className="w-full bg-teal-500 hover:bg-teal-600 disabled:bg-teal-300 disabled:cursor-not-allowed text-white text-sm font-bold py-2.5 rounded shadow-sm"
      >
        {isLoading ? 'Applying…' : 'Apply'}
      </button>
    </section>
  );
}

interface SummaryRowProps {
  label: string;
  value: string;
  valueClass?: string;
}

function SummaryRow({ label, value, valueClass = 'text-slate-900' }: SummaryRowProps) {
  return (
    <div className="bg-white border border-slate-200 rounded-md px-3 py-2 flex items-center gap-3">
      <span className="text-sm text-slate-700 font-medium min-w-[120px]">
        {label}:
      </span>
      <span className={`text-base font-bold ${valueClass}`}>{value}</span>
    </div>
  );
}
