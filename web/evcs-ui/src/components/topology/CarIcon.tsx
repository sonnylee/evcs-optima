import type { CarSnapshot } from '../../types/evcs';

interface Props {
  car: CarSnapshot;
}

export function CarIcon({ car }: Props) {
  const isActive = car.status === 'Active';
  return (
    <div className="flex items-center gap-2" data-testid={`car-${car.port_id}`}>
      <div
        className={`w-10 h-10 rounded-full flex items-center justify-center text-white text-lg shadow-sm ${
          isActive ? '' : 'opacity-80'
        }`}
        style={{ backgroundColor: car.color }}
        title={`Car ${car.port_id} • ${car.status}`}
      >
        🚗
      </div>
      <div className="flex flex-col text-xs leading-tight">
        <span className="font-semibold">Car {car.port_id}</span>
        <span className="text-slate-600 flex items-baseline gap-1">
          <span className="w-[84px]">Max. Required:</span>
          <span className="font-mono text-right tabular-nums w-10">{car.max_required}</span>
          <span>kW</span>
        </span>
        <span className="text-slate-500 flex items-baseline gap-1">
          <span className="w-[84px]">Allocated:</span>
          <span className="font-mono text-right tabular-nums w-10">{car.allocated_kw}</span>
          <span>kW</span>
          {car.priority != null ? <span>• Pri {car.priority}</span> : null}
        </span>
      </div>
    </div>
  );
}
