import { useEvcsStore } from '../../stores/evcsStore';
import { PresentField } from './PresentField';
import { PriorityField } from './PriorityField';
import { TargetField } from './TargetField';

export function Fr14ControlTable() {
  const carPorts = useEvcsStore((s) => s.carPorts);
  const systemConfig = useEvcsStore((s) => s.systemConfig);
  const maxN = systemConfig ? systemConfig.rec_bd_count * 2 : carPorts.length;

  const onApply = () => {
    // F14.3 will wire backend; this step keeps it as a noop.
    // eslint-disable-next-line no-console
    console.log('Apply and Generate — F14.3 will wire backend');
  };

  return (
    <div className="bg-slate-100 rounded-md flex flex-col h-full">
      <div className="grid grid-cols-3 bg-slate-700 text-white text-sm font-semibold rounded-t-md">
        <span className="text-center py-2">優先級</span>
        <span className="text-center py-2 border-l border-slate-600">Present</span>
        <span className="text-center py-2 border-l border-slate-600">Target</span>
      </div>
      <div className="flex-1 px-2">
        {carPorts.map((port) => {
          const others = carPorts
            .filter((p) => p.port_id !== port.port_id && p.priority != null)
            .map((p) => p.priority as number);
          return (
            <div
              key={port.port_id}
              className="grid grid-cols-3 items-center h-16 border-b border-slate-200 last:border-b-0"
            >
              <PriorityField
                portId={port.port_id}
                value={port.priority}
                allPriorities={others}
                maxN={maxN}
              />
              <PresentField portId={port.port_id} value={port.present} />
              <TargetField portId={port.port_id} value={port.target} />
            </div>
          );
        })}
      </div>
      <div className="p-3">
        <button
          type="button"
          onClick={onApply}
          className="w-full bg-teal-500 hover:bg-teal-600 text-white text-sm font-bold py-3 rounded shadow-sm"
        >
          Apply and Generate Control steps
        </button>
      </div>
    </div>
  );
}
