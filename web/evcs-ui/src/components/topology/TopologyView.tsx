import { useLayoutEffect, useRef, useState } from 'react';
import { useEvcsStore } from '../../stores/evcsStore';
import type { PackSnapshot, RelaySnapshot, RecBdSnapshot } from '../../types/evcs';
import { BridgeRelay } from './BridgeRelay';
import { CarIcon } from './CarIcon';
import { RecBdLabel } from './RecBdLabel';
import { RelayIcon } from './RelayIcon';

const CAR_ROW_HEIGHT = 64; // matches h-16 used in CarRow / Fr14ControlTable rows
const REC_BD_HEIGHT = CAR_ROW_HEIGHT * 2; // each REC BD owns 2 cars

interface GroupBlockProps {
  groupIndex: number;
  powerKw: number;
  packs: PackSnapshot[];
}

function GroupBlock({ groupIndex, powerKw, packs }: GroupBlockProps) {
  const ownerColor = packs.find((p) => p.in_use)?.color ?? '#FFFFFF';
  const inUse = packs.some((p) => p.in_use);
  return (
    <div
      className={`flex-1 flex flex-col items-center justify-center rounded border text-[11px] font-mono px-2 ${
        inUse ? 'border-slate-500 text-white' : 'border-slate-300 text-slate-600'
      }`}
      style={{ backgroundColor: ownerColor }}
      title={`Group ${groupIndex + 1} • ${powerKw}kW (${packs.length} packs)`}
    >
      <span className="font-semibold leading-none">{powerKw}kW</span>
      <span className="text-[9px] leading-none opacity-80 mt-0.5">G{groupIndex + 1}</span>
    </div>
  );
}

interface RecBdRowProps {
  recBd: RecBdSnapshot;
  packs: PackSnapshot[];
  outputRelays: RelaySnapshot[];
  interGroupRelays: RelaySnapshot[];
  cars: ReturnType<typeof groupCars>;
}

function groupCars(snapshot: ReturnType<typeof useEvcsStore.getState>['snapshot'], recBdId: number) {
  if (!snapshot) return [];
  return snapshot.cars
    .filter((c) => c.rec_bd_id === recBdId)
    .sort((a, b) => a.port_id - b.port_id);
}

interface Pt {
  x: number;
  y: number;
}

// Orthogonal "elbow" connector: horizontal → vertical → horizontal, bending at
// the horizontal midpoint between the two anchors. Renders as a 折線 rather than
// a straight diagonal so it stays clear of neighbouring blocks.
function elbowPath(a: Pt, b: Pt): string {
  const mx = (a.x + b.x) / 2;
  return `M ${a.x} ${a.y} H ${mx} V ${b.y} H ${b.x}`;
}

function RecBdRow({ recBd, packs, outputRelays, interGroupRelays, cars }: RecBdRowProps) {
  // Group packs by group_index inferred from pack.pack_index ranges.
  // We don't have group_index on PackSnapshot, but config gives module_powers.
  const systemConfig = useEvcsStore((s) => s.systemConfig);
  const recBdConfig = systemConfig?.rec_bds.find((b) => b.id === recBd.id);
  const modulePowers = recBdConfig?.module_powers ?? [50, 75, 75, 50];

  // Build pack ranges per group.
  const groups: { index: number; powerKw: number; packs: PackSnapshot[] }[] = [];
  let cursor = 0;
  modulePowers.forEach((kw, gIdx) => {
    const packCount = Math.round(kw / 25);
    const slice = packs
      .slice()
      .sort((a, b) => a.pack_index - b.pack_index)
      .filter((p) => p.pack_index >= cursor && p.pack_index < cursor + packCount);
    groups.push({ index: gIdx, powerKw: kw, packs: slice });
    cursor += packCount;
  });

  // Sort inter-group relays by id (M{n}.R2 < R3 < R4)
  const sortedInter = [...interGroupRelays].sort((a, b) => a.id.localeCompare(b.id));

  // Match output relay to car by port id.
  const outputForPort = (portId: number) =>
    outputRelays.find((r) => r.owner_port_id === portId);

  // --- Output→Group elbow connectors -------------------------------------
  // O1 (first car's output) links to the FIRST group block (G1); O2 (second
  // car's output) links to the LAST group block (G4 in the default 4-group
  // config). Anchors are measured from the live DOM so the lines track the
  // power-proportional block heights and any layout reflow.
  const rowRef = useRef<HTMLDivElement>(null);
  const firstGroupRef = useRef<HTMLDivElement>(null); // G1
  const lastGroupRef = useRef<HTMLDivElement>(null); // G4
  const o1Ref = useRef<HTMLDivElement>(null);
  const o2Ref = useRef<HTMLDivElement>(null);
  const [connectors, setConnectors] = useState<{ d: string; closed: boolean }[]>([]);

  const o1Closed = outputForPort(cars[0]?.port_id ?? -1)?.state === 'Closed';
  const o2Closed = outputForPort(cars[1]?.port_id ?? -1)?.state === 'Closed';
  const powersKey = modulePowers.join(',');

  useLayoutEffect(() => {
    const row = rowRef.current;
    if (!row) return;

    const compute = () => {
      const rb = row.getBoundingClientRect();
      const seg = (
        groupEl: HTMLDivElement | null,
        outEl: HTMLDivElement | null,
        closed: boolean,
      ) => {
        if (!groupEl || !outEl) return null;
        const g = groupEl.getBoundingClientRect();
        const o = outEl.getBoundingClientRect();
        const start: Pt = { x: g.right - rb.left, y: g.top + g.height / 2 - rb.top };
        const end: Pt = { x: o.left - rb.left, y: o.top + o.height / 2 - rb.top };
        return { d: elbowPath(start, end), closed };
      };
      const next = [
        seg(firstGroupRef.current, o1Ref.current, o1Closed),
        seg(lastGroupRef.current, o2Ref.current, o2Closed),
      ].filter((s): s is { d: string; closed: boolean } => s !== null);
      setConnectors(next);
    };

    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(row);
    return () => ro.disconnect();
  }, [o1Closed, o2Closed, powersKey, cars.length]);

  return (
    <div
      ref={rowRef}
      className="relative flex items-stretch gap-3"
      style={{ height: REC_BD_HEIGHT }}
      data-testid={`rec-bd-row-${recBd.id}`}
    >
      {/* Connector overlay — sits behind the boxes (which carry z-10) so the
          elbow lines tuck into the group / output edges. */}
      <svg
        className="absolute inset-0 h-full w-full pointer-events-none"
        style={{ zIndex: 0 }}
        aria-hidden="true"
      >
        {connectors.map((c, i) => (
          <path
            key={i}
            d={c.d}
            fill="none"
            stroke={c.closed ? '#b91c1c' : '#94a3b8'}
            strokeWidth={1.5}
            strokeDasharray="4 3"
          />
        ))}
      </svg>

      <RecBdLabel recBd={recBd} />
      {/* Group column with inter-group relay dots interleaved.
          Cluster is sized to a fraction of the column (≈105px) and
          justify-center'd so its vertical midpoint sits at 64px — aligned with
          the two car rows' combined centroid. Column height stays REC_BD_HEIGHT. */}
      <div className="relative z-10 flex flex-col justify-center w-24" style={{ height: REC_BD_HEIGHT }}>
        {groups.map((g, idx) => {
          const isFirst = idx === 0;
          const isLast = idx === groups.length - 1;
          return (
            <div key={g.index} className="flex flex-col" style={{ height: Math.max(28, g.powerKw * 0.42) }}>
              <div
                ref={isFirst ? firstGroupRef : isLast ? lastGroupRef : undefined}
                className="flex-1 flex"
              >
                <GroupBlock groupIndex={g.index} powerKw={g.powerKw} packs={g.packs} />
              </div>
              {idx < groups.length - 1 && sortedInter[idx] && (
                <div className="flex justify-center -my-1 z-10">
                  <span
                    className={`block w-3 h-3 rounded-full border ${
                      sortedInter[idx].state === 'Closed'
                        ? 'border-red-700'
                        : 'border-slate-400'
                    }`}
                    style={{ backgroundColor: sortedInter[idx].color }}
                    title={`${sortedInter[idx].id} • ${sortedInter[idx].state}`}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
      {/* Cars column — exactly 2 rows of CAR_ROW_HEIGHT to align with right panels */}
      <div className="relative z-10 flex flex-col flex-1">
        {cars.map((car, carIdx) => {
          const out = outputForPort(car.port_id);
          return (
            <div
              key={car.port_id}
              className="flex items-center gap-2"
              style={{ height: CAR_ROW_HEIGHT }}
            >
              {/* Invisible spacer reserves room for the incoming elbow connector. */}
              <span className="w-10" />
              {out && (
                <div ref={carIdx === 0 ? o1Ref : carIdx === 1 ? o2Ref : undefined}>
                  <RelayIcon relay={out} />
                </div>
              )}
              <span className="w-10 border-t border-dashed border-slate-300" />
              <CarIcon car={car} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

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
  const isRing = snapshot.rec_bds.length >= 3;

  return (
    <div className="flex flex-col gap-1" data-testid="topology-view">
      {snapshot.rec_bds.map((recBd, idx) => {
        const packs = snapshot.packs.filter((p) => p.rec_bd_id === recBd.id);
        const outputRelays = snapshot.relays.filter(
          (r) => r.kind === 'output' && r.rec_bd_id === recBd.id,
        );
        const interGroupRelays = snapshot.relays.filter(
          (r) => r.kind === 'inter_group' && r.rec_bd_id === recBd.id,
        );
        const cars = groupCars(snapshot, recBd.id);

        // After SPEC §3 flip: each REC BD owns its LEFT bridge.
        // BD 1 in a ring has the wrap (`B_{last}_{first}`) as its left bridge;
        // in linear N=2 BD 0 has no left bridge (bridgeAbove undefined).
        let bridgeAbove: typeof snapshot.relays[number] | undefined;
        if (idx === 0) {
          if (isRing) {
            const last = recBdIds[recBdIds.length - 1];
            bridgeAbove = snapshot.relays.find(
              (r) =>
                r.kind === 'bridge' &&
                (r.id === `B_${last}_${recBd.id}` || r.id === `B_${recBd.id}_${last}`),
            );
          }
        } else {
          const prevId = recBdIds[idx - 1];
          bridgeAbove = snapshot.relays.find(
            (r) =>
              r.kind === 'bridge' &&
              (r.id === `B_${prevId}_${recBd.id}` || r.id === `B_${recBd.id}_${prevId}`),
          );
        }

        return (
          <div key={recBd.id}>
            {bridgeAbove && <BridgeRelay bridge={bridgeAbove} />}
            <RecBdRow
              recBd={recBd}
              packs={packs}
              outputRelays={outputRelays}
              interGroupRelays={interGroupRelays}
              cars={cars}
            />
          </div>
        );
      })}

      {snapshot.warnings.length > 0 && (
        <div className="rounded border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-900 mt-3">
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
