import { useEvcsStore } from '../../stores/evcsStore';
import { BridgeRelay } from './BridgeRelay';
import { CarIcon } from './CarIcon';
import { PackGrid } from './PackGrid';
import { RecBdLabel } from './RecBdLabel';
import { RelayIcon } from './RelayIcon';

export function TopologyView() {
  const snapshot = useEvcsStore((s) => s.snapshot);

  if (!snapshot) {
    return (
      <div className="h-full flex items-center justify-center text-slate-400 text-sm">
        Configure a system to render the topology.
      </div>
    );
  }

  const recBdIds = snapshot.rec_bds.map((b) => b.id);

  return (
    <div className="flex flex-col gap-4">
      {snapshot.rec_bds.map((recBd) => {
        const packs = snapshot.packs.filter((p) => p.rec_bd_id === recBd.id);
        const localRelays = snapshot.relays.filter(
          (r) => r.rec_bd_id === recBd.id && r.kind !== 'bridge',
        );
        const cars = snapshot.cars.filter((c) => c.rec_bd_id === recBd.id);
        const outputRelays = localRelays.filter((r) => r.kind === 'output');
        const interGroupRelays = localRelays.filter((r) => r.kind === 'inter_group');

        // Bridges that connect *into* this REC BD from the next one in the list,
        // rendered between this REC BD and the next.
        const nextId = recBdIds[recBdIds.indexOf(recBd.id) + 1];
        const bridgeBelow = nextId
          ? snapshot.relays.find(
              (r) =>
                r.kind === 'bridge' &&
                (r.id === `B_${recBd.id}_${nextId}` || r.id === `B_${nextId}_${recBd.id}`),
            )
          : undefined;

        return (
          <div key={recBd.id}>
            <RecBdLabel recBd={recBd}>
              <PackGrid packs={packs} />
              {interGroupRelays.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {interGroupRelays.map((r) => (
                    <RelayIcon key={r.id} relay={r} />
                  ))}
                </div>
              )}
              <div className="flex justify-between gap-4">
                {cars.map((c) => {
                  const out = outputRelays.find((r) => r.owner_port_id === c.port_id);
                  return (
                    <div key={c.port_id} className="flex flex-col gap-2">
                      {out && <RelayIcon relay={out} />}
                      <CarIcon car={c} />
                    </div>
                  );
                })}
              </div>
            </RecBdLabel>
            {bridgeBelow && <BridgeRelay bridge={bridgeBelow} />}
          </div>
        );
      })}

      {/* Ring-wrap bridge (last → first) for N ≥ 3 */}
      {snapshot.rec_bds.length >= 3 &&
        (() => {
          const first = recBdIds[0];
          const last = recBdIds[recBdIds.length - 1];
          const wrap = snapshot.relays.find(
            (r) =>
              r.kind === 'bridge' &&
              (r.id === `B_${last}_${first}` || r.id === `B_${first}_${last}`),
          );
          if (!wrap) return null;
          return (
            <div className="text-center text-xs text-slate-500">
              Ring wrap (last ↔ first)
              <BridgeRelay bridge={wrap} />
            </div>
          );
        })()}

      {snapshot.warnings.length > 0 && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <strong className="block mb-1">Warnings</strong>
          <ul className="list-disc pl-4 space-y-0.5">
            {snapshot.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
