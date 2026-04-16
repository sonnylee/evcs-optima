"""Topology helpers for multi-MCU layouts.

SPEC §2.2 defines the MCU arrangement:
  * N < 4  → linear chain (bridges between consecutive MCUs only)
  * N >= 4 → ring (bridges wrap around to close the loop)

Centralizing the ring-vs-linear rules here avoids duplicating the same
arithmetic across `RelayMatrix`, `ModuleAssignment`, and `Validator`.
"""

from __future__ import annotations


def is_ring(num_mcus: int) -> bool:
    """SPEC §2.2: ring topology kicks in at 4+ MCUs."""
    return num_mcus >= 4


def adjacent_pairs(num_mcus: int) -> list[tuple[int, int]]:
    """MCU index pairs that share a physical bridge relay.

    Linear (`N < 4`): (0,1), (1,2), …, (N-2, N-1).
    Ring   (`N >= 4`): linear pairs plus (N-1, 0) to close the loop.
    Single MCU: no pairs.
    """
    if num_mcus <= 1:
        return []
    pairs = [(i, i + 1) for i in range(num_mcus - 1)]
    if is_ring(num_mcus):
        pairs.append((num_mcus - 1, 0))
    return pairs


def ring_distance(a: int, b: int, num_mcus: int) -> int:
    """Shortest hop count between two MCU indices.

    Ring topology takes the wrap-around shortcut; linear goes straight.
    """
    direct = abs(a - b)
    if is_ring(num_mcus):
        return min(direct, num_mcus - direct)
    return direct
