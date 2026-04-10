from typing import Any


class ModuleAssignment:
    """Tracks which Output owns which Groups.

    Rows = Outputs, Columns = Groups.
    Values: 0 = idle, 1 = in use, -1 = cannot assign.
    """

    def __init__(self, num_outputs: int, num_groups: int, num_mcus: int = 1):
        self.num_outputs = num_outputs
        self.num_groups = num_groups
        self._matrix: list[list[int]] = [
            [0] * num_groups for _ in range(num_outputs)
        ]
        # Mark unreachable Groups as -1 for each Output
        self._init_constraints(num_mcus)

    def _init_constraints(self, num_mcus: int) -> None:
        """For multi-MCU, Outputs can't reach Groups on non-adjacent MCUs."""
        if num_mcus <= 1:
            return  # single MCU: all Groups reachable by all Outputs
        for mcu in range(num_mcus):
            out_base = mcu * 2
            for o in range(out_base, out_base + 2):
                for other_mcu in range(num_mcus):
                    if num_mcus >= 4:
                        # Ring: distance wraps around
                        distance = min(
                            abs(other_mcu - mcu),
                            num_mcus - abs(other_mcu - mcu),
                        )
                    else:
                        # Linear: straight distance
                        distance = abs(other_mcu - mcu)
                    if distance > 1:
                        g_base = other_mcu * 4
                        for g in range(g_base, g_base + 4):
                            self._matrix[o][g] = -1

    def assign(self, output_idx: int, group_idx: int) -> None:
        assert self._matrix[output_idx][group_idx] != -1, "Cannot assign"
        self._matrix[output_idx][group_idx] = 1

    def release(self, output_idx: int, group_idx: int) -> None:
        assert self._matrix[output_idx][group_idx] != -1, "Cannot release"
        self._matrix[output_idx][group_idx] = 0

    def get_owner(self, group_idx: int) -> int | None:
        """Return the Output index that owns this Group, or None if idle."""
        for o in range(self.num_outputs):
            if self._matrix[o][group_idx] == 1:
                return o
        return None

    def get_groups_for_output(self, output_idx: int) -> list[int]:
        return [g for g in range(self.num_groups) if self._matrix[output_idx][g] == 1]

    def is_contiguous(self, output_idx: int) -> bool:
        groups = self.get_groups_for_output(output_idx)
        if len(groups) <= 1:
            return True
        groups.sort()
        return groups[-1] - groups[0] == len(groups) - 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_outputs": self.num_outputs,
            "num_groups": self.num_groups,
            "matrix": [row[:] for row in self._matrix],
        }
