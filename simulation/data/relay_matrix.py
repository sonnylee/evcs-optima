"""Per-MCU RelayMatrix — SPEC §5.1 + §10.

Each MCU owns its own instance covering a fixed 3-MCU window (left
neighbor + self + right neighbor). For ``num_mcus == 1`` the window
collapses to just self (6×6). All public methods accept **absolute**
group/output indices and translate to local on entry; calls referencing
nodes outside this MCU's window are silently rejected (``is_legal`` →
``False``, ``get_state`` → ``-1``, ``set_state`` → no-op).

This replaces the previous globally-sized shared instance — see SPEC §10:
*"每個 MCU 都擁有自已的 RelayMatrix 與 ModuleAssignment 且不做資源共享"*.
"""

from __future__ import annotations

from typing import Any

from simulation.utils.topology import (
    GROUPS_PER_MCU,
    OUTPUTS_PER_MCU,
    adjacent_pairs,
    local_window,
)

# 3-MCU window layout (SPEC §5.1):
#   local groups  : 0..3=left, 4..7=self, 8..11=right   (12 nodes)
#   local outputs : 12..13=left, 14..15=self, 16..17=right (6 nodes)
WINDOW_GROUPS_3MCU = 3 * GROUPS_PER_MCU      # 12
WINDOW_OUTPUTS_3MCU = 3 * OUTPUTS_PER_MCU    # 6
WINDOW_SIZE_3MCU = WINDOW_GROUPS_3MCU + WINDOW_OUTPUTS_3MCU  # 18


class RelayMatrix:
    """Relay adjacency matrix for one MCU's 3-MCU window."""

    def __init__(self, mcu_id: int = 0, num_mcus: int = 1):
        self.mcu_id = mcu_id
        self.num_mcus = num_mcus
        if num_mcus <= 1:
            # Single MCU: window = self only (6×6).
            self.num_groups = GROUPS_PER_MCU
            self.num_outputs = OUTPUTS_PER_MCU
            self._slot_to_mcu: list[int | None] = [mcu_id]
        else:
            self.num_groups = WINDOW_GROUPS_3MCU
            self.num_outputs = WINDOW_OUTPUTS_3MCU
            win = local_window(mcu_id, num_mcus)
            # Slot order: [left, self, right] — ``None`` in linear N==2 edges.
            self._slot_to_mcu = [win["left"], win["self"], win["right"]]
        self.size = self.num_groups + self.num_outputs
        self._matrix: list[list[int]] = [
            [-1] * self.size for _ in range(self.size)
        ]
        self._build_topology()

    # ── Topology construction ────────────────────────────────────────

    def _build_topology(self) -> None:
        """Populate adjacency for every MCU visible in this window."""
        for slot, mcu in enumerate(self._slot_to_mcu):
            if mcu is None:
                continue
            base_g = slot * GROUPS_PER_MCU
            base_o = self.num_groups + slot * OUTPUTS_PER_MCU
            # Inter-group relays: G0-G1, G1-G2, G2-G3
            for i in range(3):
                self._set_pair_local(base_g + i, base_g + i + 1, 0)
            # Output relays: O0↔G0, O1↔G3
            self._set_pair_local(base_o, base_g, 0)
            self._set_pair_local(base_o + 1, base_g + 3, 0)

        # Cross-MCU bridges between consecutive slots that both exist.
        if self.num_mcus >= 2:
            slot_pairs: list[tuple[int, int]] = []
            for left_slot in range(len(self._slot_to_mcu) - 1):
                if (
                    self._slot_to_mcu[left_slot] is not None
                    and self._slot_to_mcu[left_slot + 1] is not None
                ):
                    slot_pairs.append((left_slot, left_slot + 1))
            for left_slot, right_slot in slot_pairs:
                left_g3 = left_slot * GROUPS_PER_MCU + 3
                right_g0 = right_slot * GROUPS_PER_MCU
                # Only wire bridges that exist in the global topology
                # (defends against linear-edge cases).
                if self._is_real_bridge(
                    self._slot_to_mcu[left_slot], self._slot_to_mcu[right_slot],
                ):
                    self._set_pair_local(left_g3, right_g0, 0)

    def _is_real_bridge(self, left_mcu: int, right_mcu: int) -> bool:
        """True iff (left_mcu, right_mcu) appears in the global bridge list."""
        for a, b in adjacent_pairs(self.num_mcus):
            if (a, b) == (left_mcu, right_mcu) or (b, a) == (left_mcu, right_mcu):
                return True
        return False

    def _set_pair_local(self, a: int, b: int, value: int) -> None:
        self._matrix[a][b] = value
        self._matrix[b][a] = value

    # ── Absolute ↔ local translation ─────────────────────────────────

    def abs_to_local_group(self, abs_g: int) -> int | None:
        """Translate an absolute group index into a local slot index, or
        ``None`` if the group is outside this MCU's 3-MCU window."""
        owner_mcu = abs_g // GROUPS_PER_MCU
        for slot, mcu in enumerate(self._slot_to_mcu):
            if mcu == owner_mcu:
                return slot * GROUPS_PER_MCU + (abs_g % GROUPS_PER_MCU)
        return None

    def abs_to_local_output(self, abs_o: int) -> int | None:
        owner_mcu = abs_o // OUTPUTS_PER_MCU
        for slot, mcu in enumerate(self._slot_to_mcu):
            if mcu == owner_mcu:
                return self.num_groups + slot * OUTPUTS_PER_MCU + (abs_o % OUTPUTS_PER_MCU)
        return None

    def local_to_abs_group(self, local_g: int) -> int | None:
        slot = local_g // GROUPS_PER_MCU
        if slot < 0 or slot >= len(self._slot_to_mcu):
            return None
        owner_mcu = self._slot_to_mcu[slot]
        if owner_mcu is None:
            return None
        return owner_mcu * GROUPS_PER_MCU + (local_g % GROUPS_PER_MCU)

    def local_to_abs_output(self, local_o: int) -> int | None:
        offset = local_o - self.num_groups
        if offset < 0:
            return None
        slot = offset // OUTPUTS_PER_MCU
        if slot < 0 or slot >= len(self._slot_to_mcu):
            return None
        owner_mcu = self._slot_to_mcu[slot]
        if owner_mcu is None:
            return None
        return owner_mcu * OUTPUTS_PER_MCU + (offset % OUTPUTS_PER_MCU)

    def _translate_endpoint(self, abs_node: int) -> int | None:
        """Resolve an endpoint that may be a group or an output (absolute)."""
        # Endpoints used by callers (`Relay`, tests) flatten group and output
        # indices into a single absolute namespace where outputs follow groups.
        # The global indexing convention is: groups occupy [0, 4*N), outputs
        # occupy [4*N, 4*N + 2*N). We replicate that here.
        global_groups = GROUPS_PER_MCU * self.num_mcus
        if abs_node < global_groups:
            return self.abs_to_local_group(abs_node)
        return self.abs_to_local_output(abs_node - global_groups)

    # ── Public API (absolute indices) ────────────────────────────────

    def is_legal(self, abs_a: int, abs_b: int) -> bool:
        a = self._translate_endpoint(abs_a)
        b = self._translate_endpoint(abs_b)
        if a is None or b is None:
            return False
        return self._matrix[a][b] != -1

    def get_state(self, abs_a: int, abs_b: int) -> int:
        a = self._translate_endpoint(abs_a)
        b = self._translate_endpoint(abs_b)
        if a is None or b is None:
            return -1
        return self._matrix[a][b]

    def set_state(self, abs_a: int, abs_b: int, value: int) -> None:
        a = self._translate_endpoint(abs_a)
        b = self._translate_endpoint(abs_b)
        if a is None or b is None:
            return  # outside window — silently ignored
        assert self._matrix[a][b] != -1, (
            f"No physical wire between abs {abs_a} and abs {abs_b} in MCU{self.mcu_id} window"
        )
        self._matrix[a][b] = value
        self._matrix[b][a] = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "mcu_id": self.mcu_id,
            "num_mcus": self.num_mcus,
            "size": self.size,
            "slot_to_mcu": list(self._slot_to_mcu),
            "matrix": [row[:] for row in self._matrix],
        }
