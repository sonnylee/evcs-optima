import type { ReactNode } from 'react';
import type { RecBdSnapshot } from '../../types/evcs';

interface Props {
  recBd: RecBdSnapshot;
  children?: ReactNode;
}

export function RecBdLabel({ recBd, children }: Props) {
  const isOccupied = recBd.status === 'Occupied';
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
