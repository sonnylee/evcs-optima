from __future__ import annotations

from typing import TYPE_CHECKING, Any

from simulation.utils.topology import (
    GROUPS_PER_MCU,
    OUTPUTS_PER_MCU,
    adjacent_pairs,
    local_window,
)

if TYPE_CHECKING:
    from simulation.hardware.charging_station import ChargingStation


class Validator:
    """Consistency + boundary checks for simulation snapshots.

    Two output streams:
      1. Station-level violations — contiguous-interval / multi-owner
         aggregated from ``ChargingStation.validate()``.
      2. Boundary-consistency log entries (SPEC §9) comparing each
         adjacent MCU pair's per-MCU ``ModuleAssignment`` views over
         the cells they BOTH cover. With per-MCU ownership (SPEC §10)
         this check is now load-bearing: divergence indicates the
         protocol layer failed to keep mirrors in sync.

    The engine calls ``check(step_index)`` each step and stores results.
    ``has_failures()`` gates CSV / Timing-Diagram export.
    """

    def __init__(self, station: ChargingStation):
        self.station = station
        self.boundary_log: list[dict[str, Any]] = []
        self.violations_log: list[dict[str, Any]] = []

    def check(self, step_index: int) -> list[dict[str, Any]]:
        violations = self.station.validate()
        if violations:
            self.violations_log.append({
                "time_step": step_index,
                "violations": list(violations),
            })

        entries = self._boundary_checks(step_index)
        self.boundary_log.extend(entries)
        return entries

    # ── Boundary consistency (SPEC §9) ───────────────────────────────────

    def _boundary_checks(self, step_index: int) -> list[dict[str, Any]]:
        """For each adjacent MCU pair, compare every cell that appears in
        BOTH MCUs' 3-MCU ``ModuleAssignment`` windows. A disagreement on
        owner identity for any shared cell is flagged inconsistent."""
        station = self.station
        N = station.num_mcus
        if N <= 1:
            return []

        entries: list[dict[str, Any]] = []
        for left, right in adjacent_pairs(N):
            conflicts = self._diff_pair(left, right)
            entry: dict[str, Any] = {
                "type": "boundary_check",
                "time_step": step_index,
                "mcu_pair": [left, right],
                "result": "consistent" if not conflicts else "inconsistent",
            }
            if conflicts:
                entry["conflicts"] = conflicts
            entries.append(entry)
        return entries

    def _diff_pair(self, left_mcu: int, right_mcu: int) -> list[dict[str, Any]]:
        """Return per-cell disagreements between the two boards' MAs."""
        N = self.station.num_mcus
        boards = self.station.boards
        if not (0 <= left_mcu < len(boards) and 0 <= right_mcu < len(boards)):
            return []
        ma_left = boards[left_mcu].module_assignment
        ma_right = boards[right_mcu].module_assignment

        # MCUs visible in BOTH windows.
        win_l = set(local_window(left_mcu, N).values()) - {None}
        win_r = set(local_window(right_mcu, N).values()) - {None}
        shared_mcus = win_l & win_r

        conflicts: list[dict[str, Any]] = []
        for shared_mcu in sorted(shared_mcus):
            for g_off in range(GROUPS_PER_MCU):
                abs_g = shared_mcu * GROUPS_PER_MCU + g_off
                # Compare every output reachable in BOTH windows.
                for owner_mcu in sorted(shared_mcus):
                    for o_off in range(OUTPUTS_PER_MCU):
                        abs_o = owner_mcu * OUTPUTS_PER_MCU + o_off
                        l_local_o = ma_left.abs_to_local_output(abs_o)
                        l_local_g = ma_left.abs_to_local_group(abs_g)
                        r_local_o = ma_right.abs_to_local_output(abs_o)
                        r_local_g = ma_right.abs_to_local_group(abs_g)
                        if (
                            l_local_o is None or l_local_g is None
                            or r_local_o is None or r_local_g is None
                        ):
                            continue
                        l_val = ma_left._matrix[l_local_o][l_local_g]
                        r_val = ma_right._matrix[r_local_o][r_local_g]
                        # `-1` (unreachable) cells are static topology — not
                        # a divergence.
                        if l_val == -1 or r_val == -1:
                            continue
                        if l_val != r_val:
                            conflicts.append({
                                "group": abs_g,
                                "output": abs_o,
                                "field": "allocated_power",
                                "values": [l_val, r_val],
                            })
        return conflicts

    # ── Gate ─────────────────────────────────────────────────────────────

    def has_failures(self) -> bool:
        if self.violations_log:
            return True
        return any(e["result"] == "inconsistent" for e in self.boundary_log)

    def summary(self) -> dict[str, Any]:
        return {
            "total_boundary_checks": len(self.boundary_log),
            "inconsistent": sum(1 for e in self.boundary_log if e["result"] == "inconsistent"),
            "station_violations": len(self.violations_log),
        }
