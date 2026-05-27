from __future__ import annotations

from typing import Any, Optional

from simulation.base import SimulationModule
from simulation.data.module_assignment import ModuleAssignment
from simulation.data.relay_matrix import RelayMatrix
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

    Per SPEC §10, owns its own ``RelayMatrix`` and ``ModuleAssignment`` over a
    3-MCU window (left + self + right). Cross-MCU effects propagate via
    Borrow/Return messages, never by sharing these instances.
    """

    def __init__(
        self,
        mcu_id: int,
        event_log: RelayEventLog,
        num_mcus: int = 1,
        has_left_bridge: bool = False,
        module_powers: Optional[list[int]] = None,
    ):
        self.mcu_id = mcu_id
        self.num_mcus = num_mcus
        prefix = f"MCU{mcu_id}"
        g_base = mcu_id * 4  # global group index offset

        # Per-MCU data structures (SPEC §10).
        self.relay_matrix = RelayMatrix(mcu_id=mcu_id, num_mcus=num_mcus)
        self.module_assignment = ModuleAssignment(mcu_id=mcu_id, num_mcus=num_mcus)

        # S2.2: derive per-instance group_configs (SMR-count list). When
        # caller supplies module_powers (kW values), validate and convert;
        # otherwise fall back to the module-level GROUP_CONFIGS so existing
        # callers (tests + Sprint 1 baseline) stay byte-identical.
        if module_powers is None:
            self.group_configs: list[int] = GROUP_CONFIGS
        else:
            if len(module_powers) != 4:
                raise ValueError(
                    f"module_powers must have length 4, got {len(module_powers)}"
                )
            for p in module_powers:
                if p < 50:
                    raise ValueError(
                        f"module_powers entry {p} below 50 kW minimum"
                    )
                if p % 25 != 0:
                    raise ValueError(
                        f"module_powers entry {p} not a multiple of 25 kW"
                    )
            self.group_configs = [p // 25 for p in module_powers]

        # Build 4 SMR Groups
        self.groups: list[SMRGroup] = []
        for i, num_smrs in enumerate(self.group_configs):
            self.groups.append(SMRGroup(f"{prefix}_G{i}", num_smrs))

        # Absolute output indices used by Relay/Output to address the
        # RelayMatrix endpoint namespace (groups occupy [0, 4*N), outputs
        # follow at [4*N, 4*N + 2*N)).
        global_groups = 4 * num_mcus
        o_matrix_base = global_groups + mcu_id * 2

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
                relay_matrix=self.relay_matrix,
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
                relay_matrix=self.relay_matrix,
                matrix_idx_a=o_matrix_base + i,
                matrix_idx_b=g_base + group_idx,
            ))

        # Build left bridge relay (from prev MCU) if applicable.
        # Per SPEC §3 the bridge is on the LEFT side of each MCU; ownership
        # therefore lives on the right-hand MCU of every bridge wire.
        self.left_bridge_relay: Relay | None = None
        if has_left_bridge and num_mcus > 1:
            # +N defensive mod (SPEC §10): avoids C-port negative-mod surprise.
            prev_mcu = (mcu_id - 1 + num_mcus) % num_mcus
            self.left_bridge_relay = Relay(
                relay_id=f"{prefix}_BR",  # _BR suffix kept (orientation-agnostic)
                relay_type=RelayType.INTER_GROUP,
                is_cross_mcu=True,
                event_log=event_log,
                node_a=f"MCU{prev_mcu}_G3",
                node_b=self.groups[0].group_id,
                relay_matrix=self.relay_matrix,
                matrix_idx_a=prev_mcu * 4 + 3,
                matrix_idx_b=g_base + 0,
            )

        self.relays = list(self.output_relays) + list(self.inter_group_relays)
        if self.left_bridge_relay is not None:
            self.relays.append(self.left_bridge_relay)

        # Build 2 Outputs with fixed Phase 1 allocation
        # O0: anchor=G0, groups={G0, G1}
        # O1: anchor=G3, groups={G2, G3}
        o_assign_base = mcu_id * 2  # output index in ModuleAssignment
        self.outputs: list[Output] = [
            Output(
                f"{prefix}_O0", self.groups[0],
                [self.groups[0], self.groups[1]],
                module_assignment=self.module_assignment,
                output_idx=o_assign_base,
                group_indices=[g_base, g_base + 1],
            ),
            Output(
                f"{prefix}_O1", self.groups[3],
                [self.groups[2], self.groups[3]],
                module_assignment=self.module_assignment,
                output_idx=o_assign_base + 1,
                group_indices=[g_base + 2, g_base + 3],
            ),
        ]

    @property
    def module_powers(self) -> list[int]:
        """Per-group power (kW), derived from ``group_configs`` (×25 kW SMRs).

        Default ``[50, 75, 75, 50]`` corresponds to ``group_configs = [2, 3, 3, 2]``.
        Used by SPEC §11 per-output minimum-guarantee logic in ``mcu_control``.
        """
        return [gc * 25 for gc in self.group_configs]

    def initialize_relays(self, dt_index: int = 0) -> None:
        """Pre-close only inter-group relays on the anchor paths.

        Output relays stay OPEN until the SPEC §11 per-Output minimum-guarantee
        interval forms on vehicle arrival (default config: 125 kW).
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
