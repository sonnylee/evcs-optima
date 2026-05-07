import { useEvcsStore } from '../../stores/evcsStore';

export function PlayerWarnings() {
  const seq = useEvcsStore((s) => s.stepSequence);
  if (!seq?.warnings || seq.warnings.length === 0) return null;

  return (
    <div className="bg-amber-50 border border-amber-300 rounded-md px-3 py-2">
      <div className="text-[11px] font-semibold text-amber-800 mb-1">⚠ Warnings</div>
      <ul className="text-xs text-amber-900 list-disc pl-4 space-y-0.5">
        {seq.warnings.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
    </div>
  );
}
