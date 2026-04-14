from __future__ import annotations

import csv
import json
from typing import Any


def _format_time(seconds: float) -> str:
    total = int(seconds)
    return f"T{total}: {total // 60:02d}:{total % 60:02d}"


class VisionOutput:
    """Collects per-step snapshots and emits the SPEC §17 CSV trace.

    Columns (dynamic per MCU count, English only):
      Step | Time | Event | Outputs Ops | Relays Ops |
      M{n}.O1 | M{n}.O2 |
      M{n}.R1 | M{n}.R2 | M{n}.R3 | M{n}.R4 |
      M{n}.EV1 Available Power | M{n}.EV1 Max Require Power |
      M{n}.EV2 Available Power | M{n}.EV2 Max Require Power

    Per-MCU column meanings:
      - M{n}.O1 / M{n}.O2 : the output power-switch relay state (ON/OFF).
      - M{n}.R1           : right bridge relay to the next MCU (SPEC §2.2).
      - M{n}.R2 / R3 / R4 : inter-group relays (G0-G1, G1-G2, G2-G3).

    Blocks CSV output when the Validator reports failures.
    """

    def __init__(self, num_mcus: int, scenario_name: str = ""):
        self.num_mcus = num_mcus
        self.scenario_name = scenario_name
        self._rows: list[dict[str, Any]] = []
        self._prev_relay: dict[str, str] = {}
        # Label maps: relay_id -> "M{n}.X" for O1/O2/R1/R2/R3/R4
        self._relay_labels: dict[str, str] = self._build_relay_labels(num_mcus)

    def _build_relay_labels(self, num_mcus: int) -> dict[str, str]:
        labels: dict[str, str] = {}
        for m in range(num_mcus):
            prefix = f"MCU{m}"
            mlab = f"M{m+1}"
            # Output power-switch relays are exposed under M{n}.O{k}
            labels[f"{prefix}_R_O0"] = f"{mlab}.O1"
            labels[f"{prefix}_R_O1"] = f"{mlab}.O2"
            # 4 relays per MCU: 3 inter-group + 1 bridge
            # MCUm's right bridge is the same physical wire as MCU(m+1)'s R1
            # (left side). Label it on the right-hand MCU to preserve the
            # "R1 = left bridge of this MCU" convention.
            right_mlab = f"M{((m + 1) % num_mcus) + 1}"
            labels[f"{prefix}_BR"]   = f"{right_mlab}.R1"
            labels[f"{prefix}_R01"]  = f"{mlab}.R2"
            labels[f"{prefix}_R12"]  = f"{mlab}.R3"
            labels[f"{prefix}_R23"]  = f"{mlab}.R4"
        return labels

    # ── Ingestion ────────────────────────────────────────────────────────

    def record_snapshot(
        self,
        step_index: int,
        current_time: float,
        station_status: dict[str, Any],
        vehicles_by_output: dict[str, dict[str, Any] | None],
        new_relay_events: list[dict[str, Any]],
        arrivals: list[dict[str, Any]],
    ) -> None:
        # Unified relay state dict keyed by relay_id (output switches + inter-group + bridge)
        relay_state: dict[str, str] = {}
        for board in station_status["boards"]:
            for r in board["relays"]:
                rid = r["relay_id"]
                relay_state[rid] = "ON" if r["state"] == "CLOSED" else "OFF"

        # Split deltas: output-switch relays vs group/bridge relays
        output_ops: list[str] = []
        relay_ops: list[str] = []
        for rid, cur in relay_state.items():
            prev = self._prev_relay.get(rid)
            if prev is not None and prev != cur:
                lab = self._relay_labels.get(rid, rid)
                verb = "closed" if cur == "ON" else "opened"
                msg = f"{lab} {verb}"
                if lab.split(".")[1].startswith("O"):
                    output_ops.append(msg)
                else:
                    relay_ops.append(msg)

        event_parts: list[str] = []
        for a in arrivals:
            olab = self._relay_labels.get(
                f"{a['output_id']}".replace("_O", "_R_O"), a["output_id"]
            )
            event_parts.append(f"{a['vehicle_id']} arrived at {olab}")
        if not event_parts and new_relay_events:
            ev = new_relay_events[0]
            lab = self._relay_labels.get(ev["relay_id"], ev["relay_id"])
            verb = "closed" if ev["to_state"] == "CLOSED" else "opened"
            event_parts.append(f"{lab} {verb}")
        event_text = "; ".join(event_parts) if event_parts else "-"

        self._prev_relay = dict(relay_state)

        self._rows.append({
            "step_index": step_index,
            "time": current_time,
            "event": event_text,
            "output_ops": "; ".join(output_ops) if output_ops else "-",
            "relay_ops": "; ".join(relay_ops) if relay_ops else "-",
            "relay_state": relay_state,
            "vehicles_by_output": vehicles_by_output,
        })

    # ── Export ───────────────────────────────────────────────────────────

    def write_csv(self, path: str, validator_failed: bool = False) -> bool:
        """Write the SPEC §17 CSV. Returns False if blocked by validator."""
        if validator_failed:
            print(f"  [VisionOutput] BLOCKED: validator reported failures — CSV not written")
            return False

        headers = self._build_headers()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if self.scenario_name:
                w.writerow([self.scenario_name])
            w.writerow(headers)
            # initial row
            w.writerow(self._initial_row(len(headers)))
            for row in self._rows:
                w.writerow(self._format_row(row))
        return True

    def write_boundary_log(self, path: str, entries: list[dict[str, Any]]) -> None:
        """Emit the SPEC §9 boundary-consistency JSON log (one JSON per line)."""
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_headers(self) -> list[str]:
        headers = ["Step", "Time", "Event", "Outputs Ops", "Relays Ops"]
        for m in range(self.num_mcus):
            mlab = f"M{m+1}"
            headers += [f"{mlab}.O1", f"{mlab}.O2"]
            headers += [f"{mlab}.R{k}" for k in range(1, 5)]
            for ev in (1, 2):
                headers += [
                    f"{mlab}.EV{ev} Available Power",
                    f"{mlab}.EV{ev} Max Require Power",
                    f"{mlab}.EV{ev} SOC",
                ]
        return headers

    def _initial_row(self, ncols: int) -> list[str]:
        row = ["Init", "-", "System standby", "-", "-"]
        for _ in range(self.num_mcus):
            row += ["OFF", "OFF"]          # O1, O2 (output power-switch relays)
            row += ["OFF"] * 4             # R1..R4
            row += ["-", "-", "-", "-", "-", "-"]  # EV1/EV2: Avail, MaxReq, SOC
        return row + [""] * max(0, ncols - len(row))

    def _format_row(self, row: dict[str, Any]) -> list[str]:
        out = [
            str(row["step_index"]),
            _format_time(row["time"]),
            row["event"],
            row["output_ops"],
            row["relay_ops"],
        ]
        for m in range(self.num_mcus):
            prefix = f"MCU{m}"
            # O1/O2 = output power-switch relay states
            out.append(row["relay_state"].get(f"{prefix}_R_O0", "OFF"))
            out.append(row["relay_state"].get(f"{prefix}_R_O1", "OFF"))
            # R1 = left bridge (= previous MCU's right bridge); R2..R4 = 3 inter-group.
            # MCUm's R1 column maps to MCU(m-1)_BR to match the label side
            # (_build_relay_labels), which names every bridge after the right-hand MCU.
            if m == 0:
                out.append("OFF")
            else:
                out.append(row["relay_state"].get(f"MCU{m-1}_BR", "OFF"))
            out.append(row["relay_state"].get(f"{prefix}_R01", "OFF"))
            out.append(row["relay_state"].get(f"{prefix}_R12", "OFF"))
            out.append(row["relay_state"].get(f"{prefix}_R23", "OFF"))
            # Per-vehicle powers by output slot
            for o_idx in (0, 1):
                veh = row["vehicles_by_output"].get(f"{prefix}_O{o_idx}")
                if veh is None:
                    out += ["-", "-", "-"]
                else:
                    avail = veh.get("available_power_kw")
                    maxreq = veh.get("max_require_power_kw")
                    soc = veh.get("current_soc")
                    out.append(f"{avail:.0f}kW" if avail is not None else "-")
                    out.append(f"{maxreq:.0f}kW" if maxreq is not None else "-")
                    out.append(f"{soc:.1f}%" if soc is not None else "-")
        return out
