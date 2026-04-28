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
        <span className="text-slate-600">
          Max. Required: {car.max_required} kW
        </span>
        <span className="text-slate-500">
          Allocated: {car.allocated_kw} kW
          {car.priority != null ? ` • Pri ${car.priority}` : ''}
        </span>
      </div>
    </div>
  );
}
