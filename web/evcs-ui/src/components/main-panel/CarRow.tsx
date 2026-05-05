import { useEvcsStore } from '../../stores/evcsStore';
import type { CarPortInput } from '../../types/evcs';
import { MaxRequiredField } from './MaxRequiredField';

interface Props {
  port: CarPortInput;
}

export function CarRow({ port }: Props) {
  const nudge = useEvcsStore((s) => s.nudgeMaxRequired);

  return (
    <div className="flex items-center gap-3 h-16 px-3 border-b border-slate-100 last:border-b-0">
      <span className="text-sm text-slate-700 whitespace-nowrap">
        Car {port.port_id} - Max. Required:
      </span>
      <MaxRequiredField portId={port.port_id} value={port.max_required} />
      <span className="text-sm text-slate-600">kW</span>
      <button
        type="button"
        onClick={() => nudge(port.port_id, 25)}
        className="bg-yellow-500 hover:bg-yellow-600 text-white text-xs font-bold px-3 py-1.5 rounded shadow-sm"
        aria-label={`Increase Car ${port.port_id} by 25kW`}
      >
        +25kW
      </button>
      <button
        type="button"
        onClick={() => nudge(port.port_id, -25)}
        className="bg-red-500 hover:bg-red-600 text-white text-xs font-bold px-3 py-1.5 rounded shadow-sm"
        aria-label={`Decrease Car ${port.port_id} by 25kW`}
      >
        -25kW
      </button>
    </div>
  );
}
