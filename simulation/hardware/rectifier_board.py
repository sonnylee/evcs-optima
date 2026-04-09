from typing import Any

from simulation.base import SimulationModule
from simulation.hardware.output import Output
from simulation.hardware.relay import Relay, RelayState, RelayType
from simulation.hardware.smr_group import SMRGroup
from simulation.log.relay_event_log import RelayEventLog


# Single MCU layout: G0(50kW) - G1(75kW) - G2(75kW) - G3(50kW)
# O0 anchored to G0, O1 anchored to G3
# Phase 1 fixed allocation: O0 gets {G0,G1}=125kW, O1 gets {G2,G3}=125kW
GROUP_CONFIGS = [2, 3, 3, 2]  # num SMRs per group (×25kW each)


class RectifierBoard(SimulationModule):
    """Hardware abstraction for one MCU's rectifier board.

    Assembles SMR Groups, Relays, and Outputs into the single-MCU topology.
    """

    def __init__(self, mcu_id: int, event_log: RelayEventLog):
        self.mcu_id = mcu_id
        prefix = f"MCU{mcu_id}"

        # Build 4 SMR Groups
        self.groups: list[SMRGroup] = []
        for i, num_smrs in enumerate(GROUP_CONFIGS):
            self.groups.append(SMRGroup(f"{prefix}_G{i}", num_smrs))

        # Build inter-group relays: R_01, R_12, R_23
        self.inter_group_relays: list[Relay] = []
        for i in range(3):
            self.inter_group_relays.append(Relay(
                relay_id=f"{prefix}_R{i}{i+1}",
                relay_type=RelayType.INTER_GROUP,
                is_cross_mcu=False,
                event_log=event_log,
                node_a=self.groups[i].group_id,
                node_b=self.groups[i + 1].group_id,
            ))

        # Build output relays: R_O0 (O0↔G0), R_O1 (O1↔G3)
        self.output_relays: list[Relay] = []
        for i, group_idx in enumerate([0, 3]):
            self.output_relays.append(Relay(
                relay_id=f"{prefix}_R_O{i}",
                relay_type=RelayType.OUTPUT_SWITCH,
                is_cross_mcu=False,
                event_log=event_log,
                node_a=f"{prefix}_O{i}",
                node_b=self.groups[group_idx].group_id,
            ))

        self.relays = self.output_relays + self.inter_group_relays

        # Build 2 Outputs with fixed Phase 1 allocation
        # O0: anchor=G0, groups={G0, G1}
        # O1: anchor=G3, groups={G2, G3}
        self.outputs: list[Output] = [
            Output(f"{prefix}_O0", self.groups[0], [self.groups[0], self.groups[1]]),
            Output(f"{prefix}_O1", self.groups[3], [self.groups[2], self.groups[3]]),
        ]

    def initialize_relays(self, dt_index: int = 0) -> None:
        """Close relays for the fixed Phase 1 power allocation."""
        # O0 path: close R_O0 and R_01
        for r in [self.output_relays[0], self.inter_group_relays[0]]:
            if r.state == RelayState.OPEN:
                r.switch(dt_index)
        # O1 path: close R_O1 and R_23
        for r in [self.output_relays[1], self.inter_group_relays[2]]:
            if r.state == RelayState.OPEN:
                r.switch(dt_index)
        # R_12 stays OPEN (boundary between O0 and O1 territories)

    def step(self, dt: float) -> None:
        for relay in self.relays:
            relay.step(dt)
        for output in self.outputs:
            output.step(dt)

    def get_status(self) -> dict[str, Any]:
        return {
            "mcu_id": self.mcu_id,
            "groups": [g.get_status() for g in self.groups],
            "relays": [r.get_status() for r in self.relays],
            "outputs": [o.get_status() for o in self.outputs],
        }
