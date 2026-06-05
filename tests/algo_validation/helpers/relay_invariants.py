"""A1 + A3 — relay ↔ ownership state-consistency (settle-time). Spec F0 §4.

This is the substantive re-inclusion of inter-group / bridge relays into L2
validation after decision 2 was withdrawn (F0 proved R_01/R_23 are NOT a
standing anchor path — they open dynamically whenever they fall outside every
output's interval, e.g. a low-demand EV whose interval shrinks to the single
anchor while still charging, `mcu_control.py:877`).

**A1** (guaranteed by `_apply_global_relay_state`, `mcu_control.py:877/890/895`,
and `_compute_required_relays:913-935`): at settle, for any inter-group relay
between adjacent abs groups ``g, g+1`` in one MCU —

    relay CLOSED  ⟺  g and g+1 are co-owned by the same single output

read from that board's own ModuleAssignment (which mirrors foreign borrows,
SPEC §10). For a bridge: CLOSED ⟺ the two boundary groups it couples
(``left.G3`` / ``right.G0``) are co-owned.

The "co-owned ⟹ CLOSED" direction is unconditional. The "CLOSED ⟹ co-owned"
direction has exactly one exception:

**A3** pristine-init: a never-reconciled MCU (no group owned in its territory)
keeps its construction state — `initialize_relays:160-173` pre-closes R_01 and
R_23 with no interval behind them. Such a board's R_01/R_23 are legitimately
CLOSED-but-not-co-owned. Once the board is touched once, every relay-changing
path reconciles it, so this exception only ever covers untouched boards.

These are *state* invariants — evaluate only at quiescence (during the arrival
close / departure open / borrow transients, ownership and relay state lag each
other by design, so a per-tick evaluation would false-fail).

No current / hot-switch concept anywhere — L2 is order + state only.
"""
from __future__ import annotations

from typing import Any

from simulation.hardware.relay import RelayState
from simulation.modules.mcu_control import GROUPS_PER_MCU
from simulation.utils.topology import adjacent_pairs

# Pristine inter-group pattern from initialize_relays (R_01=CLOSED, R_12=OPEN,
# R_23=CLOSED). Indices into board.inter_group_relays.
_PRISTINE_INTERGROUP = {0: RelayState.CLOSED, 1: RelayState.OPEN, 2: RelayState.CLOSED}
# R_01 / R_23 are the only relays that may be CLOSED-but-not-co-owned (A3).
_ANCHOR_INTERGROUP_IDX = (0, 2)


def _board_is_pristine_init(board: Any) -> bool:
    """True iff the board still holds its construction relay vector
    (initialize_relays:160-173): R_01/R_23 CLOSED, R_12 OPEN, all Output relays
    OPEN, left bridge (if any) OPEN."""
    ig = board.inter_group_relays
    if len(ig) < 3:
        return False
    for idx, want in _PRISTINE_INTERGROUP.items():
        if ig[idx].state != want:
            return False
    if any(r.state != RelayState.OPEN for r in board.output_relays):
        return False
    if board.left_bridge_relay is not None and board.left_bridge_relay.state != RelayState.OPEN:
        return False
    return True


def relay_ownership_violations(engine: Any) -> list[str]:
    """Return A1/A3 violations (empty list = consistent). Call only at settle."""
    boards = engine.station.boards
    num_mcus = engine.station.num_mcus
    out: list[str] = []

    # ── A1 inter-group (+ A3 pristine exception) ─────────────────────────
    for mcu_idx, board in enumerate(boards):
        ma = board.module_assignment
        base = mcu_idx * GROUPS_PER_MCU
        owners = {base + k: ma.get_owner(base + k) for k in range(GROUPS_PER_MCU)}
        nothing_owned = all(o is None for o in owners.values())
        pristine = nothing_owned and _board_is_pristine_init(board)

        for i in range(GROUPS_PER_MCU - 1):
            g, g1 = base + i, base + i + 1
            co_owned = owners[g] is not None and owners[g] == owners[g1]
            closed = board.inter_group_relays[i].state == RelayState.CLOSED
            if co_owned and not closed:
                out.append(
                    f"M{mcu_idx}.R{i} OPEN but g{g},g{g1} co-owned by O{owners[g]}")
            elif closed and not co_owned:
                if i in _ANCHOR_INTERGROUP_IDX and pristine:
                    continue  # A3: untouched board's standing anchor path
                out.append(
                    f"M{mcu_idx}.R{i} CLOSED but g{g},g{g1} not co-owned "
                    f"(owners O{owners[g]}, O{owners[g1]})")

    # ── A1 bridge ────────────────────────────────────────────────────────
    for left, right in adjacent_pairs(num_mcus):
        bridge = engine.station.bridge_relay_between(left)
        if bridge is None:
            continue
        g_left = left * GROUPS_PER_MCU + (GROUPS_PER_MCU - 1)
        g_right = right * GROUPS_PER_MCU + 0
        owner_l = boards[left].module_assignment.get_owner(g_left)
        owner_r = boards[right].module_assignment.get_owner(g_right)
        co_owned = owner_l is not None and owner_l == owner_r
        closed = bridge.state == RelayState.CLOSED
        if co_owned and not closed:
            out.append(
                f"bridge({left},{right}) OPEN but boundary g{g_left},g{g_right} "
                f"co-owned by O{owner_l}")
        elif closed and not co_owned:
            out.append(
                f"bridge({left},{right}) CLOSED but boundary g{g_left},g{g_right} "
                f"not co-owned (owners O{owner_l}, O{owner_r})")

    return out


def required_local_intergroup_indices(interval_min: int, interval_max: int,
                                      mcu_idx: int, wrap) -> set[int]:
    """B1 helper: local inter-group relay indices that must be CLOSED for an
    output whose virtual interval is [interval_min, interval_max].

    Read-only mirror of the local-inter-group branch of
    ``_compute_required_relays`` (`mcu_control.py:913-919`): for each consecutive
    virtual pair (v, v+1) whose physical groups are consecutive and both inside
    this MCU's territory, the relay between them (index = local position) is
    required. ``wrap`` is ``mcu._wrap`` (virtual→physical)."""
    base = mcu_idx * GROUPS_PER_MCU
    needed: set[int] = set()
    for v in range(interval_min, interval_max):
        p = wrap(v)
        pn = wrap(v + 1)
        if base <= p <= base + (GROUPS_PER_MCU - 2) and pn == p + 1:
            needed.add(p - base)
    return needed
