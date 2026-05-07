import { useEvcsStore } from '../../stores/evcsStore';

export function PlayerControls() {
  const stepBack = useEvcsStore((s) => s.stepBack);
  const stepForward = useEvcsStore((s) => s.stepForward);
  const exitPlayer = useEvcsStore((s) => s.exitPlayer);

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => stepBack()}
          className="bg-slate-400 hover:bg-slate-500 text-white font-bold py-3 rounded shadow-sm text-sm"
          aria-label="Previous step"
        >
          {'<<'}
          <div className="text-[11px] font-normal opacity-90">Back</div>
        </button>
        <button
          type="button"
          onClick={() => stepForward()}
          className="bg-teal-500 hover:bg-teal-600 text-white font-bold py-3 rounded shadow-sm text-sm"
          aria-label="Next step"
        >
          {'>>'}
          <div className="text-[11px] font-normal opacity-90">Forward</div>
        </button>
      </div>
      <button
        type="button"
        onClick={() => exitPlayer()}
        className="w-full text-xs text-slate-600 hover:text-slate-900 hover:underline py-1"
      >
        ← 返回編輯模式
      </button>
    </div>
  );
}
