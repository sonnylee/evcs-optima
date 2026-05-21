import type { RelaySnapshot } from '../../types/evcs';

interface Props {
  bridge: RelaySnapshot;
}

export function BridgeRelay({ bridge }: Props) {
  const isClosed = bridge.state === 'Closed';
  return (
    <div
      className="flex items-center gap-1 h-3 pl-[134px]"
      data-testid={`bridge-${bridge.id}`}
      title={`${bridge.id} • ${bridge.state}`}
    >
      <div
        className={`w-3 h-3 rounded-full border ${
          isClosed ? 'border-red-700' : 'border-slate-400'
        }`}
        style={{ backgroundColor: bridge.color }}
      />
      <span className="text-[9px] font-mono text-slate-500">{bridge.id}</span>
    </div>
  );
}
