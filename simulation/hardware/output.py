from __future__ import annotations

from typing import TYPE_CHECKING, Any

from simulation.base import SimulationModule
from simulation.hardware.smr_group import SMRGroup

if TYPE_CHECKING:
    from simulation.data.module_assignment import ModuleAssignment
    from simulation.modules.vehicle import Vehicle


class Output(SimulationModule):
    """Charging gun endpoint — bridges Vehicle to hardware Groups."""

    def __init__(
        self,
        output_id: str,
        anchor_group: SMRGroup,
        groups: list[SMRGroup],
        module_assignment: ModuleAssignment | None = None,
        output_idx: int = -1,
        group_indices: list[int] | None = None,
    ):
        self.output_id = output_id
        self.anchor_group = anchor_group
        self.groups = groups  # all groups assigned to this output (including anchor)
        self.connected_vehicle: Vehicle | None = None
        self.available_power_kw: float = sum(g.total_power_kw for g in groups)
        self.present_power_kw: float = 0.0
        self._module_assignment = module_assignment
        self._output_idx = output_idx
        self._group_indices = group_indices or []

    def connect_vehicle(self, vehicle: Vehicle) -> None:
        self.connected_vehicle = vehicle
        vehicle.output = self
        for g in self.groups:
            g.owner_output_id = self.output_id
        if self._module_assignment is not None:
            for gi in self._group_indices:
                self._module_assignment.assign(self._output_idx, gi)

    def disconnect_vehicle(self) -> None:
        if self._module_assignment is not None:
            for gi in self._group_indices:
                self._module_assignment.release(self._output_idx, gi)
        if self.connected_vehicle:
            self.connected_vehicle.output = None
            self.connected_vehicle = None
        self.present_power_kw = 0.0
        for g in self.groups:
            g.owner_output_id = None

    def step(self, dt: float) -> None:
        pass  # Output is passive in Phase 1; Vehicle drives power negotiation

    def get_status(self) -> dict[str, Any]:
        return {
            "output_id": self.output_id,
            "connected_vehicle_id": self.connected_vehicle.vehicle_id if self.connected_vehicle else None,
            "available_power_kw": self.available_power_kw,
            "present_power_kw": self.present_power_kw,
            "groups": [g.group_id for g in self.groups],
        }
