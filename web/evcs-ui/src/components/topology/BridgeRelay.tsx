import type { RelaySnapshot } from '../../types/evcs';

interface Props {
  bridge: RelaySnapshot;
}

export function BridgeRelay({ bridge }: Props) {
  const isClosed = bridge.state === 'Closed';
  return (
    <div className="flex items-center gap-2 px-2 my-1" data-testid={`bridge-${bridge.id}`}>
      <div className="flex-1 border-t border-dashed border-slate-300" />
      <div
        className={`px-3 py-1 rounded-full border text-[10px] font-mono ${
          isClosed ? 'border-red-600 text-white' : 'border-slate-300 text-slate-700'
        }`}
        style={{ backgroundColor: bridge.color }}
      >
        Bridge {bridge.id} • {bridge.state}
      </div>
      <div className="flex-1 border-t border-dashed border-slate-300" />
    </div>
  );
}
