import { useEvcsStore } from '../../stores/evcsStore';

export function SystemStatusSummary() {
  const snapshot = useEvcsStore((s) => s.snapshot);
  const systemConfig = useEvcsStore((s) => s.systemConfig);

  if (!snapshot) return null;

  const totalCapacity = systemConfig
    ? systemConfig.rec_bds.reduce(
        (sum, bd) => sum + bd.module_powers.reduce((a, b) => a + b, 0),
        0,
      )
    : 0;

  const activeCars = snapshot.cars.filter((c) => c.status === 'Active').length;
  const totalPorts = snapshot.cars.length;

  return (
    <div className="bg-slate-700 text-white rounded-md p-4 space-y-1">
      <div className="text-xs text-slate-300 mb-1">系統狀態摘要:</div>
      <div className="text-sm font-mono">
        總輸出功率:{' '}
        <span className="font-bold">{snapshot.total_power_kw} kW</span>
        {totalCapacity > 0 && (
          <span className="text-slate-300"> / {totalCapacity} kW</span>
        )}
      </div>
      <div className="text-sm font-mono">
        充電中車輛:{' '}
        <span className="font-bold">
          {activeCars} / {totalPorts}
        </span>
      </div>
    </div>
  );
}
