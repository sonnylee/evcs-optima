from typing import Any


class RelayMatrix:
    """Relay adjacency matrix — defines physically legal connections.

    For num_mcus=1: 6×6 matrix (4 Groups + 2 Outputs).
    Indices: 0..3 = Groups, 4..5 = Outputs.
    Values: -1 = no wire, 0 = open, 1 = closed.
    """

    def __init__(self, num_mcus: int = 1):
        self.num_mcus = num_mcus
        self.num_groups = 4 * num_mcus
        self.num_outputs = 2 * num_mcus
        self.size = self.num_groups + self.num_outputs
        # Initialize all to -1 (no physical wire)
        self._matrix: list[list[int]] = [
            [-1] * self.size for _ in range(self.size)
        ]
        # Diagonal is -1 (self-connection meaningless)
        self._build_topology()

    def _build_topology(self) -> None:
        """Build adjacency for all MCUs."""
        for mcu in range(self.num_mcus):
            base_g = mcu * 4
            base_o = self.num_groups + mcu * 2

            # Inter-group relays: G0-G1, G1-G2, G2-G3
            for i in range(3):
                self._set_pair(base_g + i, base_g + i + 1, 0)

            # Output relays: O0↔G0, O1↔G3
            self._set_pair(base_o, base_g, 0)
            self._set_pair(base_o + 1, base_g + 3, 0)

            # Cross-MCU bridge: last Group of this MCU ↔ first Group of next
            if self.num_mcus > 1:
                next_mcu = (mcu + 1) % self.num_mcus
                self._set_pair(base_g + 3, next_mcu * 4, 0)

    def _set_pair(self, a: int, b: int, value: int) -> None:
        self._matrix[a][b] = value
        self._matrix[b][a] = value

    def is_legal(self, a: int, b: int) -> bool:
        return self._matrix[a][b] != -1

    def get_state(self, a: int, b: int) -> int:
        return self._matrix[a][b]

    def set_state(self, a: int, b: int, value: int) -> None:
        assert self._matrix[a][b] != -1, f"No physical wire between {a} and {b}"
        self._matrix[a][b] = value
        self._matrix[b][a] = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_mcus": self.num_mcus,
            "size": self.size,
            "matrix": [row[:] for row in self._matrix],
        }
