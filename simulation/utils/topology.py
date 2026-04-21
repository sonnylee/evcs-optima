"""Topology helpers for multi-MCU layouts.

SPEC §2.2 defines the MCU arrangement:
  * N <= 2 → linear chain (bridges between consecutive MCUs only)
  * N >= 3 → ring (bridges wrap around to close the loop)

Centralizing the ring-vs-linear rules here avoids duplicating the same
arithmetic across `RelayMatrix`, `ModuleAssignment`, and `Validator`.
"""

from __future__ import annotations

GROUPS_PER_MCU = 4
OUTPUTS_PER_MCU = 2


def is_ring(num_mcus: int) -> bool:
    """SPEC §2.2: ring topology kicks in at 3+ MCUs."""
    return num_mcus >= 3


def adjacent_pairs(num_mcus: int) -> list[tuple[int, int]]:
    """MCU index pairs that share a physical bridge relay.

    Linear (`N == 2`): (0,1).
    Ring   (`N >= 3`): (0,1), (1,2), …, (N-2, N-1), (N-1, 0).
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


def mcu_of_group(abs_group_idx: int) -> int:
    """Owning MCU id for an absolute group index. SPEC §5.2."""
    return abs_group_idx // GROUPS_PER_MCU


def mcu_of_output(abs_output_idx: int) -> int:
    """Owning MCU id for an absolute output index."""
    return abs_output_idx // OUTPUTS_PER_MCU


def local_window(self_mcu: int, num_mcus: int) -> dict[str, int | None]:
    """3-MCU window for `self_mcu` (SPEC §5.1).

    Returns ``{"left": prev, "self": self_mcu, "right": next}``. Neighbor
    slots are ``None`` only for ``num_mcus <= 1`` (no neighbors at all) or
    in the linear ``N == 2`` case where one side has no neighbor on that
    edge. SPEC §7.1 ring formula is used when ``is_ring(num_mcus)``.
    """
    if num_mcus <= 1:
        return {"left": None, "self": self_mcu, "right": None}
    if is_ring(num_mcus):
        prev_mcu: int | None = (self_mcu - 1 + num_mcus) % num_mcus
        next_mcu: int | None = (self_mcu + 1) % num_mcus
    else:  # N == 2: linear, no wrap
        prev_mcu = self_mcu - 1 if self_mcu > 0 else None
        next_mcu = self_mcu + 1 if self_mcu < num_mcus - 1 else None
    return {"left": prev_mcu, "self": self_mcu, "right": next_mcu}
