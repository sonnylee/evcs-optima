import { useEvcsStore } from '../stores/evcsStore';
import { ConfigPanel } from './config-panel/ConfigPanel';
import { TopologyView } from './topology/TopologyView';

export function App() {
  const mode = useEvcsStore((s) => s.mode);
  const globalError = useEvcsStore((s) => s.globalError);

  return (
    <div className="grid grid-cols-[400px_1fr] h-screen">
      <aside className="overflow-y-auto p-4 border-r border-slate-200 bg-white flex flex-col gap-4">
        <h1 className="text-base font-bold text-slate-900">EVCS Optima</h1>
        {globalError && (
          <div className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-900">
            {globalError}
          </div>
        )}
        {mode === 'edit' ? (
          <>
            <ConfigPanel />
            {/* CarPortPanel + ApplyAndGenerate land in Phase 2/3 */}
            <p className="text-[11px] text-slate-400 mt-2">
              Phase 1 build — Config + Topology only. Car Port input panel and step
              player arrive in later phases.
            </p>
          </>
        ) : (
          <p className="text-xs text-slate-500">Player mode (placeholder).</p>
        )}
      </aside>
      <main className="overflow-auto p-4">
        <TopologyView />
      </main>
    </div>
  );
}
