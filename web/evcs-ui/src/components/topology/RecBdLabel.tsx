import type { ReactNode } from 'react';
import type { RecBdSnapshot } from '../../types/evcs';

interface Props {
  recBd: RecBdSnapshot;
  /** Optional children (legacy callers); the new TopologyView renders the label
   *  as a self-contained vertical block and places groups / cars beside it. */
  children?: ReactNode;
}

export function RecBdLabel({ recBd, children }: Props) {
  const isOccupied = recBd.status === 'Occupied';

  if (children) {
    return (
      <section
        className="rounded-lg border border-slate-200 bg-white shadow-sm"
        data-testid={`rec-bd-${recBd.id}`}
      >
        <header
          className="flex items-center justify-between px-3 py-2 rounded-t-lg text-white text-sm font-semibold"
          style={{ backgroundColor: recBd.color }}
        >
          <span>REC BD {recBd.id}</span>
          <span className="flex items-center gap-3 text-xs opacity-95">
            <span
              className={`px-2 py-0.5 rounded-full ${
                isOccupied ? 'bg-white/25' : 'bg-black/20'
              }`}
            >
              {recBd.status}
            </span>
            <span>
              Power: {recBd.power_kw}kW ({recBd.used_packs}/{recBd.total_packs})
            </span>
          </span>
        </header>
        <div className="p-3 flex flex-col gap-3">{children}</div>
      </section>
    );
  }

  // Self-contained vertical label (used by the new TopologyView layout).
  return (
    <div
      className="flex flex-col items-center justify-center text-white rounded-md shadow-sm px-2 py-1 w-20"
      style={{ backgroundColor: recBd.color }}
      data-testid={`rec-bd-${recBd.id}`}
    >
      <span className="text-xs font-bold leading-tight">REC BD</span>
      <span className="text-lg font-extrabold leading-tight">{recBd.id}</span>
      <span
        className={`mt-1 text-[10px] px-1.5 py-0.5 rounded-full ${
          isOccupied ? 'bg-white/25' : 'bg-black/25'
        }`}
      >
        {recBd.status}
      </span>
      <span className="text-[10px] mt-1 leading-tight font-mono">
        {recBd.power_kw}kW
      </span>
      <span className="text-[9px] opacity-90 leading-tight font-mono">
        {recBd.used_packs}/{recBd.total_packs}
      </span>
    </div>
  );
}
