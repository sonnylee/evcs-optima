import type { PackSnapshot } from '../../types/evcs';

interface Props {
  packs: PackSnapshot[];
}

export function PackGrid({ packs }: Props) {
  return (
    <div className="flex flex-wrap gap-1" data-testid="pack-grid">
      {packs.map((p) => (
        <div
          key={p.pack_index}
          className={`w-9 h-9 rounded border text-[10px] font-mono flex items-center justify-center ${
            p.in_use ? 'border-slate-400 text-white' : 'border-slate-300 text-slate-500'
          }`}
          style={{ backgroundColor: p.color }}
          title={
            p.in_use
              ? `Pack ${p.pack_index} • Port ${p.owner_port_id}`
              : `Pack ${p.pack_index} • idle`
          }
        >
          {p.pack_index}
        </div>
      ))}
    </div>
  );
}
