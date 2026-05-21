import { Fragment } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import { CarRow } from './CarRow';
import { Fr14ControlTable } from './Fr14ControlTable';

// REC BD boundary: each REC BD owns exactly 2 Car Ports (FR-10 invariant),
// so the owning REC BD index is derived from port_id, NOT from the array index
// (robust to non-contiguous / unsorted carPorts and to num_mcus changes).
const recBdIndexOf = (portId: number) => Math.floor((portId - 1) / 2);

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
    <div className="grid grid-cols-2 gap-4 h-full mx-auto w-full max-w-[760px] pt-3">
      {/* Middle column — white background, FR-07/09 ±25 controls */}
      <div className="bg-white border border-slate-200 rounded-md flex flex-col">
        {carPorts.map((port, i) => {
          // Insert a 16px spacer at each REC BD boundary to mirror topology's
          // per-boundary gap-1 (4px) + bridge h-3 (12px). First BD: no spacer.
          const boundary =
            i > 0 && recBdIndexOf(port.port_id) !== recBdIndexOf(carPorts[i - 1].port_id);
          return (
            <Fragment key={port.port_id}>
              {boundary && <div style={{ height: 16 }} aria-hidden />}
              <CarRow port={port} />
            </Fragment>
          );
        })}
      </div>
      {/* Right column — gray background, FR-13/14/16 priority/present/target + Apply */}
      <Fr14ControlTable />
    </div>
  );
}
