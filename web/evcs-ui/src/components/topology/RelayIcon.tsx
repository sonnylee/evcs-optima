import type { RelaySnapshot } from '../../types/evcs';

interface Props {
  relay: RelaySnapshot;
}

export function RelayIcon({ relay }: Props) {
  const isClosed = relay.state === 'Closed';
  return (
    <div
      className={`min-w-[44px] h-6 rounded border text-[9px] font-mono px-1 flex items-center justify-center gap-1 whitespace-nowrap ${
        isClosed ? 'border-red-600 text-white' : 'border-slate-300 text-slate-700'
      }`}
      style={{ backgroundColor: relay.color }}
      title={`${relay.id} • ${relay.state}`}
    >
      <span className="font-semibold">{relay.id}</span>
    </div>
  );
}
