import { useEvcsStore } from '../../stores/evcsStore';

export function StepDescription() {
  const idx = useEvcsStore((s) => s.currentStepIndex);
  const seq = useEvcsStore((s) => s.stepSequence);

  let description = 'Initial State (Present)';
  if (seq && idx >= 1 && seq.steps && idx <= seq.total_steps) {
    description = seq.steps[idx - 1]?.description ?? '';
  }

  return (
    <div className="bg-white border border-slate-200 rounded-md p-4">
      <div className="text-xs text-slate-500 mb-2">當前步驟操作:</div>
      <div className="text-base font-semibold text-slate-900 break-words">
        {description}
      </div>
    </div>
  );
}
