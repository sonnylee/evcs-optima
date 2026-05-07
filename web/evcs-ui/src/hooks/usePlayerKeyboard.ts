import { useEffect } from 'react';
import { useEvcsStore } from '../stores/evcsStore';

export function usePlayerKeyboard() {
  const mode = useEvcsStore((s) => s.mode);
  const stepForward = useEvcsStore((s) => s.stepForward);
  const stepBack = useEvcsStore((s) => s.stepBack);
  const exitPlayer = useEvcsStore((s) => s.exitPlayer);

  useEffect(() => {
    if (mode !== 'player') return;
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
        return;
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        stepForward();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        stepBack();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        exitPlayer();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [mode, stepForward, stepBack, exitPlayer]);
}
