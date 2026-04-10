from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from simulation.environment.time_controller import TimeController
from simulation.hardware.charging_station import ChargingStation
from simulation.log.relay_event_log import RelayEventLog
from simulation.modules.vehicle import Vehicle
from simulation.utils.config_loader import SimulationConfig


class SimulationEngine:
    """Main loop driver — advances time and calls step(dt) on all modules."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.time_controller = TimeController(config.dt, config.t_end)
        self.event_log = RelayEventLog()
        self.db = TinyDB(storage=MemoryStorage)
        self.snapshots = self.db.table("snapshots")

        # Build charging station
        self.station = ChargingStation(
            mcu_id=0, event_log=self.event_log, num_mcus=config.num_mcus,
        )
        self.station.initialize(dt_index=0)

        # Create and connect vehicles
        self.vehicles: list[Vehicle] = []
        profile_map = {p.name: p for p in config.vehicle_profiles}
        outputs = self.station.rectifier_board.outputs

        for vp in config.initial_vehicles:
            profile = profile_map[vp.vehicle_profile_name]
            vehicle = Vehicle(
                vehicle_id=f"EV_{vp.output_index}",
                battery_capacity_kwh=profile.battery_capacity_kwh,
                soc_power_curve=profile.soc_power_curve,
                initial_soc=vp.initial_soc,
                target_soc=vp.target_soc,
            )
            outputs[vp.output_index].connect_vehicle(vehicle)
            self.vehicles.append(vehicle)

    def run(self) -> None:
        tc = self.time_controller
        dt = tc.dt

        while not tc.is_finished():
            # Step all vehicles first (update SOC, negotiate power)
            for vehicle in self.vehicles:
                vehicle.step(dt)

            # Step charging station (hardware updates)
            self.station.step(dt)

            # Collect snapshot
            self._collect_snapshot()

            # Advance time
            tc.tick()

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
            "relay_events": [
                e.to_dict() for e in self.event_log.get_events_at(step_idx)
            ],
            "violations": violations,
        })

    def print_summary(self) -> None:
        """Print a simple text summary of the simulation."""
        tc = self.time_controller
        print(f"Simulation complete: {tc.step_index} steps, {tc.current_time:.0f}s")
        print(f"Relay events logged: {len(self.event_log)}")
        print()

        for v in self.vehicles:
            s = v.get_status()
            print(f"  {s['vehicle_id']}: SOC {s['current_soc']:.1f}% "
                  f"(target {s['target_soc']}%), state={s['state']}")
        print()

        # Print matrix state
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

        # Print SOC progression at 10% intervals of simulation time
        all_snaps = self.snapshots.all()
        total = len(all_snaps)
        if total == 0:
            return
        print("  Time(s) | SOC(%)  | Power(kW)")
        print("  --------|---------|----------")
        for pct in range(0, 101, 10):
            idx = min(int(total * pct / 100), total - 1)
            snap = all_snaps[idx]
            for vs in snap["vehicles"]:
                print(f"  {snap['time']:7.0f} | {vs['current_soc']:6.1f}% | {vs['present_power_kw']:7.1f}")
