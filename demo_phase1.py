"""Phase 1 demo — single MCU, one vehicle, no borrowing."""

from simulation.environment.simulation_engine import SimulationEngine
from simulation.utils.config_loader import ConfigLoader


def main():
    config = ConfigLoader.load_default()
    engine = SimulationEngine(config)

    print("=== EVCS Optima — Phase 1 Demo ===")
    print(f"Config: dt={config.dt}s, t_end={config.t_end}s, MCUs={config.num_mcus}")
    print(f"Vehicles: {len(config.initial_vehicles)}")
    print()

    engine.run()
    engine.print_summary()


if __name__ == "__main__":
    main()
