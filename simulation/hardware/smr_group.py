from typing import Any

from simulation.base import SimulationModule
from simulation.hardware.smr import SMR


class SMRGroup(SimulationModule):
    """A group of SMR modules (e.g. 2×25kW=50kW or 3×25kW=75kW)."""

    def __init__(self, group_id: str, num_smrs: int):
        self.group_id = group_id
        self.smrs = [SMR(f"{group_id}_SMR{i}") for i in range(num_smrs)]
        self.owner_output_id: str | None = None

    @property
    def total_power_kw(self) -> float:
        return sum(s.rated_power_kw for s in self.smrs if s.enabled)

    def step(self, dt: float) -> None:
        for smr in self.smrs:
            smr.step(dt)

    def get_status(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "total_power_kw": self.total_power_kw,
            "owner_output_id": self.owner_output_id,
            "smrs": [s.get_status() for s in self.smrs],
        }
