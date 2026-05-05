import type { RelaySnapshot } from '../../types/evcs';

interface Props {
  bridge: RelaySnapshot;
}

export function BridgeRelay({ bridge }: Props) {
  const isClosed = bridge.state === 'Closed';
  return (
    <div
      className="flex items-center gap-2 px-1 h-3"
      data-testid={`bridge-${bridge.id}`}
      title={`${bridge.id} • ${bridge.state}`}
    >
      <div className="flex-1 border-t border-dashed border-slate-300" />
      <div
        className={`w-3 h-3 rounded-full border ${
          isClosed ? 'border-red-700' : 'border-slate-400'
        }`}
        style={{ backgroundColor: bridge.color }}
      />
      <span className="text-[9px] font-mono text-slate-500">{bridge.id}</span>
      <div className="flex-1 border-t border-dashed border-slate-300" />
    </div>
  );
}
