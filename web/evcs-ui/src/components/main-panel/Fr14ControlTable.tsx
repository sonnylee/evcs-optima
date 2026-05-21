import { Fragment } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import { PresentField } from './PresentField';
import { PriorityField } from './PriorityField';
import { TargetField } from './TargetField';

// Same REC BD boundary derivation as MainPanel: 2 Car Ports per REC BD (FR-10).
const recBdIndexOf = (portId: number) => Math.floor((portId - 1) / 2);

export function Fr14ControlTable() {
  const carPorts = useEvcsStore((s) => s.carPorts);
  const systemConfig = useEvcsStore((s) => s.systemConfig);
  const isApplying = useEvcsStore((s) => s.isApplying);
  const applyInfo = useEvcsStore((s) => s.applyInfo);
  const applyAndGenerate = useEvcsStore((s) => s.applyAndGenerate);
  const maxN = systemConfig ? systemConfig.rec_bd_count * 2 : carPorts.length;

  return (
    <div className="bg-slate-100 rounded-md flex flex-col h-full">
      <div className="grid grid-cols-3 bg-slate-700 text-white text-sm font-semibold rounded-t-md">
        <span className="text-center py-2">優先級</span>
        <span className="text-center py-2 border-l border-slate-600">Present</span>
        <span className="text-center py-2 border-l border-slate-600">Target</span>
      </div>
      <div className="flex-1 px-2">
        {carPorts.map((port, i) => {
          const others = carPorts
            .filter((p) => p.port_id !== port.port_id && p.priority != null)
            .map((p) => p.priority as number);
          // Mirror MainPanel's per-REC-BD-boundary 16px spacer so the gray column
          // stays row-aligned with the white column and topology.
          const boundary =
            i > 0 && recBdIndexOf(port.port_id) !== recBdIndexOf(carPorts[i - 1].port_id);
          return (
            <Fragment key={port.port_id}>
              {boundary && <div style={{ height: 16 }} aria-hidden />}
              <div className="grid grid-cols-3 items-center h-16 border-b border-slate-200 last:border-b-0">
                <PriorityField
                  portId={port.port_id}
                  value={port.priority}
                  allPriorities={others}
                  maxN={maxN}
                />
                <PresentField portId={port.port_id} value={port.present} />
                <TargetField portId={port.port_id} value={port.target} />
              </div>
            </Fragment>
          );
        })}
      </div>
      <div className="p-3 space-y-2">
        {applyInfo && (
          <div className="text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded px-2 py-1.5">
            {applyInfo}
          </div>
        )}
        <button
          type="button"
          onClick={() => applyAndGenerate()}
          disabled={isApplying}
          className="w-full bg-teal-500 hover:bg-teal-600 disabled:bg-teal-300 disabled:cursor-not-allowed text-white text-sm font-bold py-3 rounded shadow-sm"
        >
          {isApplying ? 'Generating control steps...' : 'Apply and Generate Control steps'}
        </button>
      </div>
    </div>
  );
}
