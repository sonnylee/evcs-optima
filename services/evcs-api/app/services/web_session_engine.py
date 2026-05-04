"""Rebuild-engine adapter — Step F09.1 (FR-09 / FR-14).

Each ``WebSessionEngine`` instance wraps **one** freshly-built
``simulation.SimulationEngine``: build with the request's demand → drive the
actor loop until borrow/return converges → read steady-state hardware →
produce a ``VisualSnapshot``. The engine is throwaway and not meant to be
reused across requests (SPEC-WEB-API §3.2 / §3.3).

Sprint 1 demo scope: **4 MCU × [50, 75, 75, 50]** only. FR-11 (dynamic
module-power configurations) lands in Sprint 2. Anything outside that
envelope raises ``ValueError`` with an explicit "Sprint 1" message.

Spike-validated state-read points (Sprint 2 must update if these change):
  - ``engine.station.boards[i].output_relays[local_idx]``
  - ``engine.station.boards[i].inter_group_relays[i]``
  - ``engine.station.boards[i].right_bridge_relay``
  - ``engine.station.boards[i].outputs[local_idx].available_power_kw``
  - ``engine.station.boards[i].module_assignment.get_owner(abs_group)``
  - ``engine._all_outputs[port_id-1]``
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple

from app.constants import (
    CAR_COLOR_ACTIVE,
    CAR_COLOR_INACTIVE,
    CAR_PORTS_PER_REC_BD,
    PACK_COLOR_IDLE,
    RELAY_COLOR_CLOSED,
    RELAY_COLOR_OPEN,
    STEP_KW,
)
from app.schemas.car_port import CarPortInput
from app.schemas.config import RecBdConfig, SystemConfig
from app.schemas.snapshot import (
    CarSnapshot,
    PackSnapshot,
    RecBdSnapshot,
    RelaySnapshot,
    VisualSnapshot,
)
from app.services.config_service import home_rec_bd_for_port, pick_palette
from simulation.communication.messages import Stop, Tick
from simulation.environment.simulation_engine import SimulationEngine
from simulation.hardware.relay import RelayState
from simulation.utils.config_loader import (
    InitialVehiclePlacement,
    SimulationConfig,
    VehicleProfile,
)


# Sprint 1 fixed envelope (FR-11 dynamic shape lands in Sprint 2).
_SPRINT1_REC_BD_COUNT = 4
_SPRINT1_MODULE_POWERS: List[int] = [50, 75, 75, 50]
_SPRINT1_ERROR = (
    "Sprint 1 demo only supports 4 MCU × [50,75,75,50]; "
    "FR-11 dynamic config arrives in Sprint 2"
)

# Convergence parameters mirror the Phase 0 spike (`SpikeRunner`).
_DEFAULT_BATTERY_KWH = 75.0
_DEFAULT_INITIAL_SOC = 30.0
_DEFAULT_TARGET_SOC = 90.0
_CONVERGE_TIMEOUT_TICKS = 200
_CONVERGE_STABLE_WINDOW = 5


def _group_to_pack_range(rec_bd_config: RecBdConfig, group_local_idx: int) -> Tuple[int, int]:
    """Return ``(pack_start, pack_end_exclusive)`` for a group within its REC BD.

    For [50, 75, 75, 50]: g0→(0,2)  g1→(2,5)  g2→(5,8)  g3→(8,10).
    Useful for Sprint 2 FR-11 too — pack ranges are derived from
    ``module_powers`` cumulatively.
    """
    start = 0
    for i, p in enumerate(rec_bd_config.module_powers):
        cnt = p // STEP_KW
        if i == group_local_idx:
            return (start, start + cnt)
        start += cnt
    raise IndexError(f"group_local_idx {group_local_idx} out of range")


class WebSessionEngine:
    """Rebuild-engine adapter for FR-09 / FR-14.

    Sprint 1 scope: 4 MCU × [50,75,75,50]. FR-11 dynamic powers → Sprint 2.

    **Construction patterns**:

    - Async path (canonical for production)::

        engine = await WebSessionEngine.create(system, ports)
        snap = engine.to_visual_snapshot()

    - Sync path (for tests with all-zero or anchor-only demand)::

        engine = WebSessionEngine(system, ports)  # no settle
        snap = engine.to_visual_snapshot()

    The sync ``__init__`` only configures anchor + initial 2 groups (~125 kW).
    Anything requiring cross-MCU borrow or > 125 kW per port must use
    ``create()``, otherwise the snapshot will reflect partial allocation.

    **Async safety**:
    Both ``create()`` and ``__init__`` are safe to call from async code.
    The sync ``__init__`` does not spin up a new event loop, so it is also
    safe inside a running FastAPI request — but its snapshot will be
    incomplete unless the demand fits the anchor-only envelope above.
    """

    def __init__(
        self,
        system_config: SystemConfig,
        car_ports: List[CarPortInput],
    ) -> None:
        """Sync constructor — only validates and builds the SimulationEngine.

        Use :meth:`WebSessionEngine.create` (async) for the full settle path.
        Direct ``__init__`` use is reserved for tests that don't need
        cross-MCU borrows (i.e. all-zero or per-port ≤ 125 kW with no
        cross-MCU demand).
        """
        self._validate_sprint1(system_config)
        self._system_config = system_config
        self._car_ports = list(car_ports)

        cfg = self._build_simulation_config(self._car_ports)
        self._engine = SimulationEngine(
            cfg, traffic_simulator=None, scenario_name="web_session"
        )
        # __init__ no longer settles — caller must use create() if demand
        # > 125 kW or cross-MCU borrow is involved.

    @classmethod
    async def create(
        cls,
        system_config: SystemConfig,
        car_ports: List[CarPortInput],
    ) -> "WebSessionEngine":
        """Async factory — builds the engine and drives the actor settle loop.

        This is the canonical entry point for FR-09 and FR-14 paths.
        Required when any port's ``max_required > 125`` kW or cross-MCU
        borrow is needed (the sync constructor only completes anchor +
        initial groups via ``handle_vehicle_arrival``).
        """
        instance = cls(system_config, car_ports)
        if any(p.max_required > 0 for p in instance._car_ports):
            await instance._settle_until_stable()
        return instance

    # ── Validation ───────────────────────────────────────────────────────

    @staticmethod
    def _validate_sprint1(system_config: SystemConfig) -> None:
        if system_config.rec_bd_count != _SPRINT1_REC_BD_COUNT:
            raise ValueError(_SPRINT1_ERROR)
        for bd in system_config.rec_bds:
            if list(bd.module_powers) != _SPRINT1_MODULE_POWERS:
                raise ValueError(_SPRINT1_ERROR)

    # ── Simulation-config translation ───────────────────────────────────

    @staticmethod
    def _flat_curve(kw: int) -> List[Tuple[float, float]]:
        return [(0.0, float(kw)), (100.0, float(kw))]

    def _build_simulation_config(self, car_ports: List[CarPortInput]) -> SimulationConfig:
        profiles: Dict[int, VehicleProfile] = {}
        placements: List[InitialVehiclePlacement] = []
        for port in car_ports:
            if port.max_required <= 0:
                continue
            kw = port.max_required
            name = f"web_port_{port.port_id}"
            profiles[port.port_id] = VehicleProfile(
                name=name,
                battery_capacity_kwh=_DEFAULT_BATTERY_KWH,
                soc_power_curve=self._flat_curve(kw),
            )
            placements.append(
                InitialVehiclePlacement(
                    vehicle_profile_name=name,
                    output_index=port.port_id - 1,
                    initial_soc=_DEFAULT_INITIAL_SOC,
                    target_soc=_DEFAULT_TARGET_SOC,
                )
            )
        return SimulationConfig(
            dt=1.0,
            t_end=1e9,
            num_mcus=_SPRINT1_REC_BD_COUNT,
            vehicle_profiles=list(profiles.values()),
            initial_vehicles=placements,
        )

    # ── Convergence (mirrors the Phase 0 SpikeRunner) ───────────────────

    async def _settle_until_stable(self) -> None:
        engine = self._engine
        actor_tasks = [asyncio.create_task(m.run()) for m in engine.mcu_controls]
        try:
            tc = engine.time_controller
            dt = tc.dt
            baseline = len(engine.event_log)
            last = baseline
            stable_streak = 0
            for _ in range(_CONVERGE_TIMEOUT_TICKS):
                for mcu in engine.mcu_controls:
                    mcu._step_index = tc.step_index
                for vehicle in engine.vehicles:
                    vehicle.step(dt)
                engine._trigger_departures()
                done_events = [asyncio.Event() for _ in engine.mcu_controls]
                for mcu, ev in zip(engine.mcu_controls, done_events):
                    await mcu.send(Tick(dt=dt, step_index=tc.step_index, done=ev))
                await asyncio.gather(*(e.wait() for e in done_events))
                await asyncio.sleep(0)
                engine.station.step(dt)
                tc.tick()
                cur = len(engine.event_log)
                if cur == last and self._all_pending_clear():
                    stable_streak += 1
                    if stable_streak >= _CONVERGE_STABLE_WINDOW:
                        break
                else:
                    stable_streak = 0
                last = cur
        finally:
            for m in engine.mcu_controls:
                await m.send(Stop())
            await asyncio.gather(*actor_tasks, return_exceptions=True)

    def _all_pending_clear(self) -> bool:
        for mcu in self._engine.mcu_controls:
            for s in mcu._output_states:
                if (
                    s.pending_intergroup_close != 0
                    or s.pending_output_relay_close != 0
                    or s.pending_intergroup_open != 0
                    or s.pending_output_relay_open != 0
                ):
                    return False
        return True

    # ── Snapshot extraction ──────────────────────────────────────────────

    def to_visual_snapshot(self, palette_cycle: bool = True) -> VisualSnapshot:
        system = self._system_config
        ports_by_id: Dict[int, CarPortInput] = {p.port_id: p for p in self._car_ports}
        palette = pick_palette(system.rec_bd_count, cycle=palette_cycle)
        color_by_bd = {i + 1: c for i, c in enumerate(palette)}
        num_mcus = system.rec_bd_count

        # Pack ownership map keyed by (rec_bd_id, pack_index).
        pack_owner: Dict[Tuple[int, int], int] = {}
        for mcu_idx, board in enumerate(self._engine.station.boards):
            rec_bd = system.rec_bds[mcu_idx]
            for g_local in range(len(rec_bd.module_powers)):
                abs_g = mcu_idx * 4 + g_local
                owner_abs = board.module_assignment.get_owner(abs_g)
                if owner_abs is None:
                    continue
                owner_port_id = owner_abs + 1
                lo, hi = _group_to_pack_range(rec_bd, g_local)
                for pack_idx in range(lo, hi):
                    pack_owner[(rec_bd.id, pack_idx)] = owner_port_id

        # --- REC BD snapshots (FR-02) ---------------------------------------
        rec_bd_snaps: List[RecBdSnapshot] = []
        for bd in system.rec_bds:
            used = sum(1 for (b, _) in pack_owner if b == bd.id)
            rec_bd_snaps.append(
                RecBdSnapshot(
                    id=bd.id,
                    color=color_by_bd[bd.id],
                    status="Occupied" if used > 0 else "Idle",
                    power_kw=used * STEP_KW,
                    used_packs=used,
                    total_packs=bd.pack_count,
                )
            )

        # --- Pack snapshots (FR-03) -----------------------------------------
        pack_snaps: List[PackSnapshot] = []
        for bd in system.rec_bds:
            for idx in range(bd.pack_count):
                owner = pack_owner.get((bd.id, idx))
                if owner is None:
                    pack_snaps.append(
                        PackSnapshot(
                            rec_bd_id=bd.id,
                            pack_index=idx,
                            in_use=False,
                            owner_port_id=None,
                            color=PACK_COLOR_IDLE,
                        )
                    )
                else:
                    owner_home = home_rec_bd_for_port(owner)
                    pack_snaps.append(
                        PackSnapshot(
                            rec_bd_id=bd.id,
                            pack_index=idx,
                            in_use=True,
                            owner_port_id=owner,
                            color=color_by_bd[owner_home],
                        )
                    )

        # --- Relay snapshots (FR-04) ----------------------------------------
        relays: List[RelaySnapshot] = []
        for mcu_idx, board in enumerate(self._engine.station.boards):
            rec_bd_id = mcu_idx + 1
            # Output relays → "M{n}.O{1|2}"
            for local_idx, relay in enumerate(board.output_relays):
                state = self._state_label(relay.state)
                port_id = mcu_idx * CAR_PORTS_PER_REC_BD + local_idx + 1
                relays.append(
                    RelaySnapshot(
                        id=f"M{rec_bd_id}.O{local_idx + 1}",
                        kind="output",
                        state=state,
                        color=self._relay_color(state),
                        owner_port_id=port_id,
                        rec_bd_id=rec_bd_id,
                    )
                )
            # Inter-group relays → "M{n}.R{i+2}" for i ∈ 0..M-2
            for i, relay in enumerate(board.inter_group_relays):
                state = self._state_label(relay.state)
                relays.append(
                    RelaySnapshot(
                        id=f"M{rec_bd_id}.R{i + 2}",
                        kind="inter_group",
                        state=state,
                        color=self._relay_color(state),
                        owner_port_id=None,
                        rec_bd_id=rec_bd_id,
                    )
                )
        # Bridge relays → "B_{a}_{b}" (right bridge owned by left MCU).
        for mcu_idx, board in enumerate(self._engine.station.boards):
            if board.right_bridge_relay is None:
                continue
            a = mcu_idx + 1
            b = (mcu_idx + 1) % num_mcus + 1
            state = self._state_label(board.right_bridge_relay.state)
            relays.append(
                RelaySnapshot(
                    id=f"B_{a}_{b}",
                    kind="bridge",
                    state=state,
                    color=self._relay_color(state),
                    owner_port_id=None,
                    rec_bd_id=None,
                )
            )

        # --- Car snapshots (FR-05) ------------------------------------------
        car_snaps: List[CarSnapshot] = []
        total_allocated = 0
        for port_id in range(1, system.car_port_count + 1):
            mcu_idx = (port_id - 1) // CAR_PORTS_PER_REC_BD
            local_idx = (port_id - 1) % CAR_PORTS_PER_REC_BD
            board = self._engine.station.boards[mcu_idx]
            output = board.outputs[local_idx]
            output_relay = board.output_relays[local_idx]
            cp = ports_by_id.get(port_id)
            max_req = cp.max_required if cp else 0
            allocated_kw = int(output.available_power_kw) if output_relay.state == RelayState.CLOSED else 0
            active = output_relay.state == RelayState.CLOSED and max_req > 0
            car_snaps.append(
                CarSnapshot(
                    port_id=port_id,
                    rec_bd_id=home_rec_bd_for_port(port_id),
                    status="Active" if active else "Inactive",
                    color=CAR_COLOR_ACTIVE if active else CAR_COLOR_INACTIVE,
                    max_required=max_req,
                    allocated_kw=allocated_kw,
                    priority=cp.priority if cp else None,
                )
            )
            total_allocated += allocated_kw

        return VisualSnapshot(
            rec_bds=rec_bd_snaps,
            packs=pack_snaps,
            relays=relays,
            cars=car_snaps,
            total_power_kw=total_allocated,
            total_requested_kw=sum(p.max_required for p in self._car_ports),
            warnings=[],
        )

    # ── State / color helpers ───────────────────────────────────────────

    @staticmethod
    def _state_label(state: RelayState) -> str:
        return "Closed" if state == RelayState.CLOSED else "Open"

    @staticmethod
    def _relay_color(state_label: str) -> str:
        return RELAY_COLOR_CLOSED if state_label == "Closed" else RELAY_COLOR_OPEN
