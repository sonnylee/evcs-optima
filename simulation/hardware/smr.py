from typing import Any

from simulation.base import SimulationModule


class SMR(SimulationModule):
    """Switching Mode Rectifier — 25kW minimum power unit."""

    def __init__(self, smr_id: str, rated_power_kw: float = 25.0):
        self.smr_id = smr_id
        self.rated_power_kw = rated_power_kw
        self.enabled = True

    def step(self, dt: float) -> None:
        pass  # no-op in Phase 1

    def get_status(self) -> dict[str, Any]:
        return {
            "smr_id": self.smr_id,
            "rated_power_kw": self.rated_power_kw,
            "enabled": self.enabled,
        }
