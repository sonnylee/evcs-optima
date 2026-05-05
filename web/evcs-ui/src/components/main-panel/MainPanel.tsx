import { useEvcsStore } from '../../stores/evcsStore';
import { CarRow } from './CarRow';
import { Fr14ControlTable } from './Fr14ControlTable';

export function MainPanel() {
  const carPorts = useEvcsStore((s) => s.carPorts);

  if (carPorts.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-slate-400 text-sm">
        Apply a configuration to enable car port controls.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 h-full">
      {/* Middle column — white background, FR-07/09 ±25 controls */}
      <div className="bg-white border border-slate-200 rounded-md flex flex-col">
        {carPorts.map((port) => (
          <CarRow key={port.port_id} port={port} />
        ))}
      </div>
      {/* Right column — gray background, FR-13/14/16 priority/present/target + Apply */}
      <Fr14ControlTable />
    </div>
  );
}
