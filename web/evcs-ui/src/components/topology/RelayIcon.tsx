import type { RelaySnapshot } from '../../types/evcs';

interface Props {
  relay: RelaySnapshot;
}

export function RelayIcon({ relay }: Props) {
  const isClosed = relay.state === 'Closed';
  return (
    <div
      className={`min-w-[58px] h-7 rounded border text-[10px] font-mono px-2 flex items-center justify-center gap-1 ${
        isClosed ? 'border-red-600 text-white' : 'border-slate-300 text-slate-700'
      }`}
      style={{ backgroundColor: relay.color }}
      title={`${relay.id} • ${relay.state}`}
    >
      <span className="font-semibold">{relay.id}</span>
    </div>
  );
}
