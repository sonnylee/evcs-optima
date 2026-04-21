"""Per-MCU ModuleAssignment — SPEC §5.2 + §10.

Each MCU owns its own instance covering a fixed 3-MCU window (left
neighbor + self + right neighbor). For ``num_mcus == 1`` the window
collapses to just self (2 outputs × 4 groups).

All public methods accept and return **absolute** Output / Group indices;
translation to the local 3-MCU window is internal. Indices outside the
window are silently rejected (``assign_if_idle`` → ``False``,
``get_owner`` → ``None``, etc.) — cross-MCU borrow/return is restricted
to immediate neighbors per SPEC §11, so non-neighbor calls indicate a
caller bug, not a missed mutation.
"""

from __future__ import annotations

from typing import Any

from simulation.utils.topology import (
    GROUPS_PER_MCU,
    OUTPUTS_PER_MCU,
    local_window,
    ring_distance,
)

WINDOW_GROUPS_3MCU = 3 * GROUPS_PER_MCU      # 12
WINDOW_OUTPUTS_3MCU = 3 * OUTPUTS_PER_MCU    # 6


class ModuleAssignment:
    """Tracks which Output owns which Groups, scoped to one MCU's window."""

    def __init__(self, mcu_id: int = 0, num_mcus: int = 1):
        self.mcu_id = mcu_id
        self.num_mcus = num_mcus
        if num_mcus <= 1:
            self.num_outputs = OUTPUTS_PER_MCU
            self.num_groups = GROUPS_PER_MCU
            self._slot_to_mcu: list[int | None] = [mcu_id]
        else:
            self.num_outputs = WINDOW_OUTPUTS_3MCU
            self.num_groups = WINDOW_GROUPS_3MCU
            win = local_window(mcu_id, num_mcus)
            self._slot_to_mcu = [win["left"], win["self"], win["right"]]
        self._matrix: list[list[int]] = [
            [0] * self.num_groups for _ in range(self.num_outputs)
        ]
        self._init_constraints()

    def _init_constraints(self) -> None:
        """Mark cells as -1 where the GLOBAL ring distance between the
        Output's MCU and the Group's MCU exceeds 1 (SPEC §2.2: borrow only
        between physically adjacent MCUs)."""
        if self.num_mcus <= 1:
            return  # everything reachable
        for o_slot, o_mcu in enumerate(self._slot_to_mcu):
            if o_mcu is None:
                continue
            for g_slot, g_mcu in enumerate(self._slot_to_mcu):
                if g_mcu is None:
                    continue
                if ring_distance(o_mcu, g_mcu, self.num_mcus) > 1:
                    o_base = o_slot * OUTPUTS_PER_MCU
                    g_base = g_slot * GROUPS_PER_MCU
                    for o_off in range(OUTPUTS_PER_MCU):
                        for g_off in range(GROUPS_PER_MCU):
                            self._matrix[o_base + o_off][g_base + g_off] = -1

    # ── Absolute ↔ local translation ─────────────────────────────────

    def abs_to_local_output(self, abs_o: int) -> int | None:
        owner_mcu = abs_o // OUTPUTS_PER_MCU
        for slot, mcu in enumerate(self._slot_to_mcu):
            if mcu == owner_mcu:
                return slot * OUTPUTS_PER_MCU + (abs_o % OUTPUTS_PER_MCU)
        return None

    def abs_to_local_group(self, abs_g: int) -> int | None:
        owner_mcu = abs_g // GROUPS_PER_MCU
        for slot, mcu in enumerate(self._slot_to_mcu):
            if mcu == owner_mcu:
                return slot * GROUPS_PER_MCU + (abs_g % GROUPS_PER_MCU)
        return None

    def local_to_abs_output(self, local_o: int) -> int | None:
        slot = local_o // OUTPUTS_PER_MCU
        if slot < 0 or slot >= len(self._slot_to_mcu):
            return None
        owner_mcu = self._slot_to_mcu[slot]
        if owner_mcu is None:
            return None
        return owner_mcu * OUTPUTS_PER_MCU + (local_o % OUTPUTS_PER_MCU)

    def local_to_abs_group(self, local_g: int) -> int | None:
        slot = local_g // GROUPS_PER_MCU
        if slot < 0 or slot >= len(self._slot_to_mcu):
            return None
        owner_mcu = self._slot_to_mcu[slot]
        if owner_mcu is None:
            return None
        return owner_mcu * GROUPS_PER_MCU + (local_g % GROUPS_PER_MCU)

    # ── Public API (absolute indices) ────────────────────────────────

    def assign(self, abs_output_idx: int, abs_group_idx: int) -> None:
        o = self.abs_to_local_output(abs_output_idx)
        g = self.abs_to_local_group(abs_group_idx)
        if o is None or g is None:
            return
        assert self._matrix[o][g] != -1, "Cannot assign"
        for other in range(self.num_outputs):
            if other != o and self._matrix[other][g] == 1:
                raise AssertionError(
                    f"Group {abs_group_idx} already owned by Output "
                    f"{self.local_to_abs_output(other)}; cannot assign to "
                    f"Output {abs_output_idx}"
                )
        self._matrix[o][g] = 1

    def assign_if_idle(self, abs_output_idx: int, abs_group_idx: int) -> bool:
        """Atomically claim `abs_group_idx` for `abs_output_idx` iff no other
        in-window Output owns it. Returns True on successful claim. Returns
        False (no mutation) if either index is outside the window."""
        o = self.abs_to_local_output(abs_output_idx)
        g = self.abs_to_local_group(abs_group_idx)
        if o is None or g is None:
            return False
        if self._matrix[o][g] == -1:
            return False
        for other in range(self.num_outputs):
            if other != o and self._matrix[other][g] == 1:
                return False
        self._matrix[o][g] = 1
        return True

    def release(self, abs_output_idx: int, abs_group_idx: int) -> None:
        o = self.abs_to_local_output(abs_output_idx)
        g = self.abs_to_local_group(abs_group_idx)
        if o is None or g is None:
            return
        if self._matrix[o][g] == -1:
            return
        self._matrix[o][g] = 0

    def get_owner(self, abs_group_idx: int) -> int | None:
        """Return the absolute Output index that owns this Group within
        this MCU's window, or None if idle / not in window."""
        g = self.abs_to_local_group(abs_group_idx)
        if g is None:
            return None
        for o in range(self.num_outputs):
            if self._matrix[o][g] == 1:
                return self.local_to_abs_output(o)
        return None

    def is_assignable(self, abs_output_idx: int, abs_group_idx: int) -> bool:
        o = self.abs_to_local_output(abs_output_idx)
        g = self.abs_to_local_group(abs_group_idx)
        if o is None or g is None:
            return False
        return self._matrix[o][g] != -1

    def get_groups_for_output(self, abs_output_idx: int) -> list[int]:
        """Return list of ABSOLUTE group indices currently held by this
        Output within this MCU's window. Empty list if the output is
        outside the window."""
        o = self.abs_to_local_output(abs_output_idx)
        if o is None:
            return []
        out: list[int] = []
        for g in range(self.num_groups):
            if self._matrix[o][g] == 1:
                abs_g = self.local_to_abs_group(g)
                if abs_g is not None:
                    out.append(abs_g)
        return out

    def is_contiguous(self, abs_output_idx: int, ring: bool = False) -> bool:
        groups = self.get_groups_for_output(abs_output_idx)
        if len(groups) <= 1:
            return True
        groups.sort()
        if groups[-1] - groups[0] == len(groups) - 1:
            return True
        if ring:
            # Wrap-around contiguity uses the GLOBAL group count, not the
            # window size — wrap math is across the whole ring.
            N = GROUPS_PER_MCU * self.num_mcus
            gaps = [(groups[(i + 1) % len(groups)] - groups[i]) % N
                    for i in range(len(groups))]
            return sum(1 for d in gaps if d != 1) == 1
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mcu_id": self.mcu_id,
            "num_mcus": self.num_mcus,
            "num_outputs": self.num_outputs,
            "num_groups": self.num_groups,
            "slot_to_mcu": list(self._slot_to_mcu),
            "matrix": [row[:] for row in self._matrix],
        }
