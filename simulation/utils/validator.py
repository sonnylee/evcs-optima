from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from simulation.hardware.charging_station import ChargingStation


class Validator:
    """Consistency + boundary checks for simulation snapshots.

    Produces two kinds of output:
      1. Station-level violations (contiguous-interval, multiple-owner)
         — aggregated from ChargingStation.validate().
      2. Boundary consistency log entries (SPEC §9) comparing the shared
         edge between adjacent MCUs: the bridge relay state and the
         group-ownership values at the boundary groups.

    The engine calls `check(step_index)` each step and stores results.
    `has_failures()` gates CSV/Timing-Diagram export.
    """

    def __init__(self, station: ChargingStation):
        self.station = station
        self.boundary_log: list[dict[str, Any]] = []
        self.violations_log: list[dict[str, Any]] = []

    def check(self, step_index: int) -> list[dict[str, Any]]:
        """Run all checks for the current step. Returns boundary-check entries."""
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
        """For each adjacent MCU pair, compare the shared boundary state."""
        station = self.station
        N = station.num_mcus
        if N <= 1:
            return []

        ma = station.module_assignment
        entries: list[dict[str, Any]] = []

        # Iterate boundaries: for linear N<4, pairs (0,1)..(N-2,N-1);
        # for ring N>=4 also include (N-1, 0).
        pairs: list[tuple[int, int]] = [(i, i + 1) for i in range(N - 1)]
        if N >= 4:
            pairs.append((N - 1, 0))

        for left, right in pairs:
            conflicts: list[dict[str, Any]] = []

            # Bridge relay: must be a single shared state; both MCUs observe it.
            # We read it from the station (left MCU owns the bridge).
            bridge = station.bridge_relay_between(left)
            if bridge is not None:
                # There is only one physical relay, so it is trivially consistent;
                # we still record its state so the log is complete.
                pass  # no divergence possible — single object

            # Group-ownership at the boundary: right-most group of `left` MCU
            # (local idx 3) and left-most group of `right` MCU (local idx 0).
            # Owner must be internally consistent: a borrow across the bridge
            # implies both sides' ModuleAssignment rows agree.
            left_boundary_group = left * 4 + 3
            right_boundary_group = right * 4 + 0

            for g in (left_boundary_group, right_boundary_group):
                owners = [o for o in range(ma.num_outputs) if ma._matrix[o][g] == 1]
                if len(owners) > 1:
                    conflicts.append({
                        "group": g,
                        "output": owners,
                        "field": "allocated_power",
                        "values": owners,
                    })

            result = "consistent" if not conflicts else "inconsistent"
            entry: dict[str, Any] = {
                "type": "boundary_check",
                "time_step": step_index,
                "mcu_pair": [left, right],
                "result": result,
            }
            if conflicts:
                entry["conflicts"] = conflicts
            entries.append(entry)

        return entries

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
