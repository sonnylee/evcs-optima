from __future__ import annotations

from typing import TYPE_CHECKING, Any

from simulation.base import SimulationModule
from simulation.hardware.output import Output
from simulation.hardware.relay import Relay, RelayState, RelayType
from simulation.hardware.smr_group import SMRGroup
from simulation.log.relay_event_log import RelayEventLog

if TYPE_CHECKING:
    from simulation.data.module_assignment import ModuleAssignment
    from simulation.data.relay_matrix import RelayMatrix


# Single MCU layout: G0(50kW) - G1(75kW) - G2(75kW) - G3(50kW)
# O0 anchored to G0, O1 anchored to G3
# Phase 1 fixed allocation: O0 gets {G0,G1}=125kW, O1 gets {G2,G3}=125kW
GROUP_CONFIGS = [2, 3, 3, 2]  # num SMRs per group (×25kW each)


class RectifierBoard(SimulationModule):
    """Hardware abstraction for one MCU's rectifier board.

    Assembles SMR Groups, Relays, and Outputs into the single-MCU topology.
    """

    def __init__(
        self,
        mcu_id: int,
        event_log: RelayEventLog,
        relay_matrix: RelayMatrix | None = None,
        module_assignment: ModuleAssignment | None = None,
        num_mcus: int = 1,
        has_right_bridge: bool = False,
    ):
        self.mcu_id = mcu_id
        self.num_mcus = num_mcus
        prefix = f"MCU{mcu_id}"
        g_base = mcu_id * 4  # global group index offset

        # Build 4 SMR Groups
        self.groups: list[SMRGroup] = []
        for i, num_smrs in enumerate(GROUP_CONFIGS):
            self.groups.append(SMRGroup(f"{prefix}_G{i}", num_smrs))

        # Compute matrix indices for relay endpoints
        num_groups = relay_matrix.num_groups if relay_matrix else 0
        o_matrix_base = num_groups + mcu_id * 2  # output index in RelayMatrix

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
                relay_matrix=relay_matrix,
                matrix_idx_a=g_base + i,
                matrix_idx_b=g_base + i + 1,
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
                relay_matrix=relay_matrix,
                matrix_idx_a=o_matrix_base + i,
                matrix_idx_b=g_base + group_idx,
            ))

        # Build right bridge relay (to next MCU) if applicable
        self.right_bridge_relay: Relay | None = None
        if has_right_bridge and num_mcus > 1:
            next_mcu = (mcu_id + 1) % num_mcus
            self.right_bridge_relay = Relay(
                relay_id=f"{prefix}_BR",
                relay_type=RelayType.INTER_GROUP,
                is_cross_mcu=True,
                event_log=event_log,
                node_a=self.groups[3].group_id,
                node_b=f"MCU{next_mcu}_G0",
                relay_matrix=relay_matrix,
                matrix_idx_a=g_base + 3,
                matrix_idx_b=next_mcu * 4,
            )

        self.relays = list(self.output_relays) + list(self.inter_group_relays)
        if self.right_bridge_relay is not None:
            self.relays.append(self.right_bridge_relay)

        # Build 2 Outputs with fixed Phase 1 allocation
        # O0: anchor=G0, groups={G0, G1}
        # O1: anchor=G3, groups={G2, G3}
        o_assign_base = mcu_id * 2  # output index in ModuleAssignment
        self.outputs: list[Output] = [
            Output(
                f"{prefix}_O0", self.groups[0],
                [self.groups[0], self.groups[1]],
                module_assignment=module_assignment,
                output_idx=o_assign_base,
                group_indices=[g_base, g_base + 1],
            ),
            Output(
                f"{prefix}_O1", self.groups[3],
                [self.groups[2], self.groups[3]],
                module_assignment=module_assignment,
                output_idx=o_assign_base + 1,
                group_indices=[g_base + 2, g_base + 3],
            ),
        ]

    def initialize_relays(self, dt_index: int = 0) -> None:
        """Pre-close only inter-group relays on the anchor paths.

        Output relays stay OPEN; they close only after the 125 kW interval
        is formed when a vehicle arrives (SPEC §11 minimum-guaranteed-power).
        """
        # O0 anchor path: close R_01
        # O1 anchor path: close R_23
        for r in [self.inter_group_relays[0], self.inter_group_relays[2]]:
            if r.state == RelayState.OPEN:
                r.switch(dt_index)
        # R_12 stays OPEN (boundary between O0 and O1 territories)
        # Output relays stay OPEN until handle_vehicle_arrival() triggers them

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
