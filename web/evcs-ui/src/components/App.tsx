import { useState } from 'react';
import { useEvcsStore } from '../stores/evcsStore';
import { ConfigPanel } from './config-panel/ConfigPanel';
import { MainPanel } from './main-panel/MainPanel';
import { StepPlayer } from './player-panel/StepPlayer';
import { TopologyView } from './topology/TopologyView';

export function App() {
  const mode = useEvcsStore((s) => s.mode);
  const globalError = useEvcsStore((s) => s.globalError);
  const sessionId = useEvcsStore((s) => s.sessionId);
  const [configOpen, setConfigOpen] = useState(!sessionId);

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="flex items-center justify-between px-4 py-2 bg-white border-b border-slate-200 shadow-sm">
        <h1 className="text-base font-bold text-slate-900">EVCS Optima</h1>
        {mode === 'edit' && (
          <button
            type="button"
            onClick={() => setConfigOpen((v) => !v)}
            className="text-xs px-3 py-1 rounded border border-slate-300 hover:bg-slate-100"
          >
            {configOpen ? 'Hide Config' : 'Show Config'}
          </button>
        )}
      </header>

      {globalError && (
        <div className="px-4 py-2 bg-red-50 border-b border-red-200 text-xs text-red-900">
          {globalError}
        </div>
      )}

      {mode === 'edit' && configOpen && (
        <div className="px-4 py-3 bg-white border-b border-slate-200">
          <ConfigPanel />
        </div>
      )}

      {mode === 'edit' ? (
        <main className="grid grid-cols-[minmax(420px,1.1fr)_minmax(620px,1.6fr)] gap-4 p-4">
          <section className="overflow-auto">
            <TopologyView />
          </section>
          <MainPanel />
        </main>
      ) : (
        <main className="grid grid-cols-[minmax(420px,1.5fr)_minmax(360px,1fr)] gap-4 p-4">
          <section className="overflow-auto">
            <TopologyView />
          </section>
          <StepPlayer />
        </main>
      )}
    </div>
  );
}
