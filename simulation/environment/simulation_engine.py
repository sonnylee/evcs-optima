import asyncio

from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from simulation.communication.messages import Stop, Tick
from simulation.environment.time_controller import TimeController
from simulation.environment.vision_output import VisionOutput
from simulation.hardware.charging_station import ChargingStation
from simulation.log.relay_event_log import RelayEventLog
from simulation.modules.mcu_control import MCUControl
from simulation.modules.traffic_simulator import TrafficSimulator
from simulation.modules.vehicle import Vehicle, VehicleState
from simulation.utils.config_loader import SimulationConfig
from simulation.utils.validator import Validator


class SimulationEngine:
    """Main loop driver.

    Uses asyncio + Queue (Actor Model) when num_mcus > 1 so MCUs can
    exchange borrow/return protocol messages. Falls back to a synchronous
    loop for single-MCU configs (Phase 3 back-compat).
    """

    def __init__(
        self,
        config: SimulationConfig,
        traffic_simulator: TrafficSimulator | None = None,
        scenario_name: str = "",
    ):
        self.config = config
        self.scenario_name = scenario_name
        self.time_controller = TimeController(config.dt, config.t_end)
        self.event_log = RelayEventLog()
        self.db = TinyDB(storage=MemoryStorage)
        self.snapshots = self.db.table("snapshots")

        self.station = ChargingStation(
            mcu_id=0, event_log=self.event_log, num_mcus=config.num_mcus,
        )
        self.station.initialize(dt_index=0)

        # Phase 5 additions: validator + CSV trace writer
        self.validator = Validator(self.station)
        self.vision = VisionOutput(num_mcus=config.num_mcus, scenario_name=scenario_name)
        self.traffic_simulator = traffic_simulator
        self._last_arrivals_count = 0
        self._last_event_count = 0

        # Connect vehicles to outputs across all MCUs
        self.vehicles: list[Vehicle] = []
        profile_map = {p.name: p for p in config.vehicle_profiles}
        all_outputs = [o for b in self.station.boards for o in b.outputs]
        self._all_outputs = all_outputs

        _initial_connections: list[tuple[int, Vehicle]] = []
        for vp in config.initial_vehicles:
            profile = profile_map[vp.vehicle_profile_name]
            vehicle = Vehicle(
                vehicle_id=f"EV_{vp.output_index}",
                battery_capacity_kwh=profile.battery_capacity_kwh,
                soc_power_curve=profile.soc_power_curve,
                initial_soc=vp.initial_soc,
                target_soc=vp.target_soc,
            )
            all_outputs[vp.output_index].connect_vehicle(vehicle)
            self.vehicles.append(vehicle)
            _initial_connections.append((vp.output_index, vehicle))

        # One MCUControl per MCU; each receives ITS OWN board's per-MCU
        # RelayMatrix and ModuleAssignment instance (SPEC §10).
        self.mcu_controls: list[MCUControl] = [
            MCUControl(
                mcu_id=i,
                board=self.station.boards[i],
                module_assignment=self.station.boards[i].module_assignment,
                relay_matrix=self.station.boards[i].relay_matrix,
                event_log=self.event_log,
                station=self.station,
                num_mcus=config.num_mcus,
                consecutive_threshold=config.consecutive_threshold,
            )
            for i in range(config.num_mcus)
        ]

        # Wire neighbors (ring for N>=3, linear otherwise)
        N = config.num_mcus
        for i, mcu in enumerate(self.mcu_controls):
            if N >= 3:
                mcu.left_neighbor = self.mcu_controls[(i - 1) % N]
                mcu.right_neighbor = self.mcu_controls[(i + 1) % N]
            else:
                mcu.left_neighbor = self.mcu_controls[i - 1] if i > 0 else None
                mcu.right_neighbor = self.mcu_controls[i + 1] if i < N - 1 else None

        # Notify MCUs about initial vehicle connections so intervals + relays
        # reflect the anchor + 2-group starting state (SPEC §6.1).
        for output_index, _vehicle in _initial_connections:
            mcu_idx = output_index // 2
            local_idx = output_index % 2
            self.mcu_controls[mcu_idx].handle_vehicle_arrival(local_idx)

        # Let TrafficSimulator notify MCUControl on dynamic arrivals.
        if self.traffic_simulator is not None:
            self.traffic_simulator.mcu_controls = self.mcu_controls

        # Drop construction-time relay switches (station.initialize + initial
        # handle_vehicle_arrival) so the trace starts from a clean ledger.
        self.event_log.clear()

    # ── Public entry point ───────────────────────────────────────────

    def run(self) -> None:
        if self.config.num_mcus <= 1:
            self._run_sync()
        else:
            asyncio.run(self._run_async())

    # ── Synchronous path (single MCU) ────────────────────────────────

    def _run_sync(self) -> None:
        tc = self.time_controller
        dt = tc.dt
        if self.traffic_simulator is not None:
            self.traffic_simulator.mcu_controls = self.mcu_controls
            self.traffic_simulator.prime_initial_arrivals()
            self._sync_traffic_vehicles()
        while not tc.is_finished():
            if self.traffic_simulator is not None:
                self.traffic_simulator.step(dt)
                self._sync_traffic_vehicles()
            for vehicle in self.vehicles:
                vehicle.step(dt)
            self._trigger_departures()
            for mcu in self.mcu_controls:
                mcu.step(dt)
            self.station.step(dt)
            self._collect_snapshot()
            tc.tick()
            if self._all_charging_complete():
                break

    # ── Async path (multi-MCU) ───────────────────────────────────────

    async def _run_async(self) -> None:
        # Launch MCU actors
        actor_tasks = [asyncio.create_task(m.run()) for m in self.mcu_controls]
        try:
            await self._driver_loop()
        finally:
            # Stop all actors
            for m in self.mcu_controls:
                await m.send(Stop())
            await asyncio.gather(*actor_tasks, return_exceptions=True)

    async def _driver_loop(self) -> None:
        tc = self.time_controller
        dt = tc.dt
        if self.traffic_simulator is not None:
            self.traffic_simulator.mcu_controls = self.mcu_controls
            self.traffic_simulator.prime_initial_arrivals()
            self._sync_traffic_vehicles()
        while not tc.is_finished():
            # Align MCU clocks with the sim clock before arrivals dispatch.
            # Relay opens driven by handle_vehicle_arrival (conflict release,
            # SPEC §6.3) fire before the Tick; without this, they get tagged
            # with the previous step's index and end up orphaned in the
            # RelayEventLog — visible as state-column changes with an empty
            # "Relays Ops" column in the trace CSV.
            for mcu in self.mcu_controls:
                mcu._step_index = tc.step_index
            if self.traffic_simulator is not None:
                self.traffic_simulator.step(dt)
                self._sync_traffic_vehicles()
            # Vehicles step first (update SOC, negotiate power)
            for vehicle in self.vehicles:
                vehicle.step(dt)
            self._trigger_departures()

            # Broadcast Tick; collect per-MCU done events
            done_events = [asyncio.Event() for _ in self.mcu_controls]
            for mcu, ev in zip(self.mcu_controls, done_events):
                await mcu.send(Tick(dt=dt, step_index=tc.step_index, done=ev))
            await asyncio.gather(*(e.wait() for e in done_events))

            # Drain any lingering protocol replies: wait until all queues empty
            await asyncio.sleep(0)

            self.station.step(dt)
            self._collect_snapshot()
            tc.tick()
            if self._all_charging_complete():
                break

    def _all_charging_complete(self) -> bool:
        """True when there is ≥1 active vehicle and every connected EV has
        reached its target SOC (scenario-finished predicate). Holds off while
        any MCU is still mid-departure so the §11 open sequence can finish."""
        active = [o.connected_vehicle for o in self._all_outputs
                  if o.connected_vehicle is not None]
        if not active:
            # Scenario finished if we've ever had vehicles, they've all
            # completed + departed, and nothing more is scheduled to arrive.
            if not self.vehicles:
                return False
            if not all(v.state == VehicleState.COMPLETE for v in self.vehicles):
                return False
            ts = self.traffic_simulator
            if ts is not None and len(ts._pending) > 0:
                return False
            return True
        if not all(v.current_soc >= v.target_soc for v in active):
            return False
        for mcu in self.mcu_controls:
            for s in mcu._output_states:
                if (s.pending_intergroup_open != 0
                        or s.pending_output_relay_open != 0):
                    return False
        return True

    # ── Shared helpers ───────────────────────────────────────────────

    def _trigger_departures(self) -> None:
        """SPEC §11: when a connected EV reaches COMPLETE, kick off the
        phased departure sequence on its owning MCU (once)."""
        for i, o in enumerate(self._all_outputs):
            v = o.connected_vehicle
            if v is None or v.state != VehicleState.COMPLETE:
                continue
            mcu_idx, local_idx = i // 2, i % 2
            self.mcu_controls[mcu_idx].initiate_vehicle_departure(local_idx)

    def _sync_traffic_vehicles(self) -> None:
        """Mirror TrafficSimulator-spawned vehicles into self.vehicles."""
        ts = self.traffic_simulator
        if ts is None:
            return
        known = {id(v) for v in self.vehicles}
        for v in ts.vehicles:
            if id(v) not in known:
                self.vehicles.append(v)

    def _collect_snapshot(self) -> None:
        step_idx = self.time_controller.step_index
        violations = self.station.validate()
        if violations:
            for v in violations:
                print(f"  [WARN] step {step_idx}: {v}")

        # Run validator (boundary consistency, SPEC §9)
        self.validator.check(step_idx)

        station_status = self.station.get_status()

        # Feed VisionOutput: per-step snapshot for CSV trace (SPEC §17)
        from simulation.hardware.relay import RelayState
        vehicles_by_output: dict[str, dict | None] = {}
        for i, o in enumerate(self._all_outputs):
            mcu_idx, local_idx = i // 2, i % 2
            out_relay = self.station.boards[mcu_idx].output_relays[local_idx]
            # SPEC §11: Available/Max-Required Power are only meaningful once
            # the Output relay is actually CLOSED (power gated to the gun).
            if (
                o.connected_vehicle is not None
                and out_relay.state == RelayState.CLOSED
            ):
                vehicles_by_output[o.output_id] = {
                    "vehicle_id": o.connected_vehicle.vehicle_id,
                    "available_power_kw": o.available_power_kw,
                    "max_require_power_kw": o.connected_vehicle.max_require_power_kw,
                    "present_power_kw": o.present_power_kw,
                    "current_soc": o.connected_vehicle.current_soc,
                }
            else:
                vehicles_by_output[o.output_id] = None

        new_events = [e.to_dict() for e in self.event_log.get_events_at(step_idx)]
        arrivals_log = self.traffic_simulator.arrivals_log if self.traffic_simulator else []
        new_arrivals = arrivals_log[self._last_arrivals_count:]
        self._last_arrivals_count = len(arrivals_log)

        self.vision.record_snapshot(
            step_index=step_idx,
            current_time=self.time_controller.current_time,
            station_status=station_status,
            vehicles_by_output=vehicles_by_output,
            new_relay_events=new_events,
            arrivals=new_arrivals,
        )

        self.snapshots.insert({
            "step_index": step_idx,
            "time": self.time_controller.current_time,
            "vehicles": [v.get_status() for v in self.vehicles],
            "station": station_status,
            "mcu_controls": [m.get_status() for m in self.mcu_controls],
            "relay_events": new_events,
            "violations": violations,
        })

    # ── Phase 5 exports ──────────────────────────────────────────────────

    def export_csv(self, path: str) -> bool:
        """Write the SPEC §17 trace CSV. Blocked if validator failed."""
        return self.vision.write_csv(path, validator_failed=self.validator.has_failures())

    def export_boundary_log(self, path: str) -> None:
        """Write the SPEC §9 boundary-consistency JSON log."""
        self.vision.write_boundary_log(path, self.validator.boundary_log)

    def print_summary(self) -> None:
        tc = self.time_controller
        print(f"Simulation complete: {tc.step_index} steps, {tc.current_time:.0f}s")
        print(f"Relay events logged: {len(self.event_log)}")
        print()

        for v in self.vehicles:
            s = v.get_status()
            print(f"  {s['vehicle_id']}: SOC {s['current_soc']:.1f}% "
                  f"(target {s['target_soc']}%), state={s['state']}")
        print()

        # Per-MCU snapshots (SPEC §10) — each board owns its own view.
        for board in self.station.boards:
            rm = board.relay_matrix
            ma = board.module_assignment
            print(f"MCU{board.mcu_id} Relay Matrix (0=open, 1=closed, -1=no wire):")
            for r in range(rm.size):
                print(f"  {rm._matrix[r]}")
            print(f"MCU{board.mcu_id} Module Assignment (0=idle, 1=in use, -1=unreachable):")
            for o in range(ma.num_outputs):
                print(f"  O{o}: {ma._matrix[o]}")
            print()

        all_snaps = self.snapshots.all()
        total = len(all_snaps)
        if total == 0:
            return
        print("  Time(s) | VehID | SOC(%)  | Power(kW)")
        print("  --------|-------|---------|----------")
        for pct in range(0, 101, 10):
            idx = min(int(total * pct / 100), total - 1)
            snap = all_snaps[idx]
            for vs in snap["vehicles"]:
                print(f"  {snap['time']:7.0f} | {vs['vehicle_id']:5s} | "
                      f"{vs['current_soc']:6.1f}% | {vs['present_power_kw']:7.1f}")
