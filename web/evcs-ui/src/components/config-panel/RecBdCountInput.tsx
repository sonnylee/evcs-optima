import { REC_BD_MAX, REC_BD_MIN } from '../../utils/validation';

interface Props {
  value: number;
  onChange: (next: number) => void;
}

export function RecBdCountInput({ value, onChange }: Props) {
  const out_of_range = value < REC_BD_MIN || value > REC_BD_MAX;
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-slate-700">
        REC BD Count
      </label>
      <input
        type="number"
        min={REC_BD_MIN}
        max={REC_BD_MAX}
        value={value}
        onChange={(e) => {
          const n = parseInt(e.target.value, 10);
          if (!Number.isNaN(n)) onChange(n);
        }}
        className={`w-24 px-2 py-1 text-sm rounded border ${
          out_of_range ? 'border-red-500 ring-1 ring-red-300' : 'border-slate-300'
        }`}
      />
      <span className="text-[10px] text-slate-500">
        Range [{REC_BD_MIN}, {REC_BD_MAX}]; each REC BD → 2 Car Ports.
      </span>
      {out_of_range && (
        <span className="text-[10px] text-red-600">
          Value out of range — must be between {REC_BD_MIN} and {REC_BD_MAX}.
        </span>
      )}
    </div>
  );
}
