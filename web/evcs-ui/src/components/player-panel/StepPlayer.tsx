import { usePlayerKeyboard } from '../../hooks/usePlayerKeyboard';
import { PlayerControls } from './PlayerControls';
import { StepDescription } from './StepDescription';
import { StepProgress } from './StepProgress';
import { SystemStatusSummary } from './SystemStatusSummary';

export function StepPlayer() {
  usePlayerKeyboard();

  return (
    <aside className="flex flex-col gap-3" data-testid="step-player">
      <div className="bg-slate-700 text-white text-center py-2 rounded-md font-semibold text-sm">
        Control Steps Player
      </div>

      <StepProgress />
      <StepDescription />
      <SystemStatusSummary />

      <div className="flex-1" />

      <PlayerControls />
    </aside>
  );
}
