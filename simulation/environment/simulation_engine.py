import asyncio

from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from simulation.communication.messages import Stop, Tick
from simulation.environment.time_controller import TimeController
from simulation.hardware.charging_station import ChargingStation
from simulation.log.relay_event_log import RelayEventLog
from simulation.modules.mcu_control import MCUControl
from simulation.modules.vehicle import Vehicle
from simulation.utils.config_loader import SimulationConfig


class SimulationEngine:
    """Main loop driver.

    Uses asyncio + Queue (Actor Model) when num_mcus > 1 so MCUs can
    exchange borrow/return protocol messages. Falls back to a synchronous
    loop for single-MCU configs (Phase 3 back-compat).
    """

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.time_controller = TimeController(config.dt, config.t_end)
        self.event_log = RelayEventLog()
        self.db = TinyDB(storage=MemoryStorage)
        self.snapshots = self.db.table("snapshots")

        self.station = ChargingStation(
            mcu_id=0, event_log=self.event_log, num_mcus=config.num_mcus,
        )
        self.station.initialize(dt_index=0)

        # Connect vehicles to outputs across all MCUs
        self.vehicles: list[Vehicle] = []
        profile_map = {p.name: p for p in config.vehicle_profiles}
        all_outputs = [o for b in self.station.boards for o in b.outputs]

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

        # One MCUControl per MCU
        self.mcu_controls: list[MCUControl] = [
            MCUControl(
                mcu_id=i,
                board=self.station.boards[i],
                module_assignment=self.station.module_assignment,
                relay_matrix=self.station.relay_matrix,
                event_log=self.event_log,
                station=self.station,
                num_mcus=config.num_mcus,
            )
            for i in range(config.num_mcus)
        ]

        # Wire neighbors (ring for N>=4, linear otherwise)
        N = config.num_mcus
        for i, mcu in enumerate(self.mcu_controls):
            if N >= 4:
                mcu.left_neighbor = self.mcu_controls[(i - 1) % N]
                mcu.right_neighbor = self.mcu_controls[(i + 1) % N]
            else:
                mcu.left_neighbor = self.mcu_controls[i - 1] if i > 0 else None
                mcu.right_neighbor = self.mcu_controls[i + 1] if i < N - 1 else None

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
        while not tc.is_finished():
            for vehicle in self.vehicles:
                vehicle.step(dt)
            for mcu in self.mcu_controls:
                mcu.step(dt)
            self.station.step(dt)
            self._collect_snapshot()
            tc.tick()

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
        while not tc.is_finished():
            # Vehicles step first (update SOC, negotiate power)
            for vehicle in self.vehicles:
                vehicle.step(dt)

            # Broadcast Tick; collect per-MCU done events
            done_events = [asyncio.Event() for _ in self.mcu_controls]
            for mcu, ev in zip(self.mcu_controls, done_events):
                await mcu.send(Tick(dt=dt, step_index=tc.step_index + 1, done=ev))
            await asyncio.gather(*(e.wait() for e in done_events))

            # Drain any lingering protocol replies: wait until all queues empty
            await asyncio.sleep(0)

            self.station.step(dt)
            self._collect_snapshot()
            tc.tick()

    # ── Shared helpers ───────────────────────────────────────────────

    def _collect_snapshot(self) -> None:
        step_idx = self.time_controller.step_index
        violations = self.station.validate()
        if violations:
            for v in violations:
                print(f"  [WARN] step {step_idx}: {v}")
        self.snapshots.insert({
            "step_index": step_idx,
            "time": self.time_controller.current_time,
            "vehicles": [v.get_status() for v in self.vehicles],
            "station": self.station.get_status(),
            "mcu_controls": [m.get_status() for m in self.mcu_controls],
            "relay_events": [
                e.to_dict() for e in self.event_log.get_events_at(step_idx)
            ],
            "violations": violations,
        })

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

        rm = self.station.relay_matrix
        ma = self.station.module_assignment
        print("Relay Matrix (0=open, 1=closed, -1=no wire):")
        for r in range(rm.size):
            print(f"  {rm._matrix[r]}")
        print()
        print("Module Assignment (0=idle, 1=in use, -1=unreachable):")
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
