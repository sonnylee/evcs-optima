import { useEvcsStore } from '../../stores/evcsStore';

export function StepProgress() {
  const idx = useEvcsStore((s) => s.currentStepIndex);
  const total = useEvcsStore((s) => s.stepSequence?.total_steps ?? 0);

  return (
    <div className="bg-white border border-slate-200 rounded-md p-4 text-center">
      <div className="text-xs text-slate-500 mb-1">步驟進度</div>
      <div className="text-3xl font-bold text-slate-900">
        Step {idx} / {total}
      </div>
    </div>
  );
}
