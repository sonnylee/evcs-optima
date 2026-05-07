import { useEvcsStore } from '../../stores/evcsStore';
import type { SystemConfig } from '../../types/evcs';

const SPRINT1_REC_BD_COUNT = 4;
const SPRINT1_MODULE_POWERS = [50, 75, 75, 50];
const SPRINT1_MODULE_POWERS_RAW = SPRINT1_MODULE_POWERS.join(', ');

export function ConfigPanel() {
  const systemConfig = useEvcsStore((s) => s.systemConfig);
  const isLoading = useEvcsStore((s) => s.isLoading);
  const updateSystemConfig = useEvcsStore((s) => s.updateSystemConfig);

  const recBdCount = systemConfig?.rec_bd_count ?? SPRINT1_REC_BD_COUNT;
  const modulePowers =
    systemConfig?.rec_bds[0]?.module_powers ?? SPRINT1_MODULE_POWERS;
  const totalCapacityKw = recBdCount * modulePowers.reduce((a, b) => a + b, 0);
  const totalPorts = recBdCount * 2;

  const onApply = async () => {
    const cfg: SystemConfig = {
      rec_bd_count: SPRINT1_REC_BD_COUNT,
      rec_bds: Array.from({ length: SPRINT1_REC_BD_COUNT }, (_, i) => ({
        id: i + 1,
        module_powers: [...SPRINT1_MODULE_POWERS],
      })),
    };
    await updateSystemConfig(cfg);
  };

  return (
    <section className="flex flex-col gap-3" data-testid="config-panel">
      <div className="bg-slate-700 text-white text-center py-2 rounded-md font-semibold text-sm">
        配置 (Configuration)
      </div>

      <ReadOnlyField
        label="REC BD 數量"
        value={String(recBdCount)}
        note="動態 REC BD 配置 Sprint 2 上線"
      />

      <ReadOnlyField
        label="REC BD 模塊配置"
        value={SPRINT1_MODULE_POWERS_RAW}
        note="動態 module power 配置 Sprint 2 上線"
      />

      <SummaryRow
        label="總容量"
        value={`${totalCapacityKw} kW`}
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
          {recBdCount} REC BD × {modulePowers.length} Groups × 2 Outputs = {totalPorts} Cars
        </div>
      </div>

      <button
        type="button"
        onClick={onApply}
        disabled={isLoading}
        className="w-full bg-teal-500 hover:bg-teal-600 disabled:bg-teal-300 disabled:cursor-not-allowed text-white text-sm font-bold py-2.5 rounded shadow-sm"
      >
        {isLoading ? 'Applying…' : 'Apply'}
      </button>
    </section>
  );
}

interface ReadOnlyFieldProps {
  label: string;
  value: string;
  note: string;
}

function ReadOnlyField({ label, value, note }: ReadOnlyFieldProps) {
  return (
    <div className="bg-white border border-slate-200 rounded-md px-3 py-2 flex items-center gap-3 flex-wrap">
      <span className="text-sm text-slate-700 font-medium min-w-[120px]">
        {label}:
      </span>
      <input
        type="text"
        value={value}
        disabled
        readOnly
        className="flex-1 max-w-[220px] px-2 py-1 bg-slate-100 text-slate-600 border border-slate-200 rounded font-mono text-sm cursor-not-allowed"
      />
      <span className="text-[11px] text-amber-700 italic">{note}</span>
    </div>
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
