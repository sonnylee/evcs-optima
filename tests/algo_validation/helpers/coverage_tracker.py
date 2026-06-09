"""``CoverageTracker`` — observational coverage over the (O, L) state space.

Spec §2 / §6. Three views, all *diagnostic* — coverage is never a pass/fail
gate (§9 note), only reported:

  - **Nodes / 766** (main KPI): key = ``(occupancy_byte, L_code)``.
    766 = 1 empty node ``(0, ⊥)`` + 255 occupancies × 3 SOC buckets.
  - **Vehicle classes / 70** (diagnostic): occupancy canonicalised under the
    C4 rotation of the four MCUs.
  - **Edges** (diagnostic): count of recorded state transitions.

``O`` is supplied by ``reuse_adapters.read_state_from_snapshot`` (reconstructed
from live outputs, C3). ``L`` (last-arrival SOC bucket) is **lossy and tracked
here from the injection side** (§2.1): ``L`` is set when an arrival is injected,
is ``⊥`` when the station is empty (``O == 0``), and is unchanged by a departure.
It is *never* reconstructed from a snapshot — the engine does not retain "the
last arrival's bucket".
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

_SOC_LEVELS = ("low", "mid", "high")
_NODE_TOTAL = 766
_CLASS_TOTAL = 70


class CoverageTracker:
    def __init__(self, num_outputs: int = 8) -> None:
        if num_outputs % 2 != 0:
            raise ValueError("num_outputs must be even (2 per MCU)")
        self.num_outputs = num_outputs
        self.num_mcus = num_outputs // 2
        # L tracking (injection side).
        self._last_L: Optional[str] = None
        # Coverage state.
        self.visited_nodes: set[tuple[int, Optional[str]]] = set()
        self.visited_classes: set[int] = set()
        self.edges: dict[tuple, int] = {}
        self._prev_key: Optional[tuple[int, Optional[str]]] = None
        # Stagnation bookkeeping (step index of the most recent new node).
        self.last_new_node_step: int = 0

    # ── L tracking (injection side, §2.1) ────────────────────────────────

    def note_arrival(self, soc_level: str) -> None:
        """Record that an arrival with ``soc_level`` was just injected → L."""
        if soc_level not in _SOC_LEVELS:
            raise ValueError(f"soc_level must be one of {_SOC_LEVELS}, got {soc_level!r}")
        self._last_L = soc_level

    def current_L(self, occupancy: int) -> Optional[str]:
        """L for the given occupancy: ⊥ (None) when empty, else the tracked
        last-arrival bucket (§2.1)."""
        return None if occupancy == 0 else self._last_L

    # ── Recording ────────────────────────────────────────────────────────

    def record(self, occupancy: int, step_index: int) -> tuple[int, Optional[str]]:
        """Record a visit to state ``(occupancy, L)`` at ``step_index``.

        Returns the node key. Resets the tracked L to ⊥ once the station is
        empty (§2.1: O=0 → ⊥).
        """
        L = self.current_L(occupancy)
        key = (occupancy, L)
        if key not in self.visited_nodes:
            self.visited_nodes.add(key)
            self.last_new_node_step = step_index
        if occupancy != 0:
            self.visited_classes.add(self._canonical(occupancy))
        if self._prev_key is not None and self._prev_key != key:
            self.edges[(self._prev_key, key)] = self.edges.get((self._prev_key, key), 0) + 1
        self._prev_key = key
        if occupancy == 0:
            self._last_L = None
        return key

    # ── C4 vehicle-class canonicalisation ────────────────────────────────

    def _canonical(self, occupancy: int) -> int:
        """Minimum occupancy over the ``num_mcus`` rotations of the MCU chunks
        (each MCU = 2 output bits)."""
        n = self.num_mcus
        chunks = [(occupancy >> (2 * k)) & 0b11 for k in range(n)]
        best: Optional[int] = None
        for r in range(n):
            rot = chunks[r:] + chunks[:r]
            val = 0
            for k, c in enumerate(rot):
                val |= c << (2 * k)
            best = val if best is None else min(best, val)
        return best if best is not None else 0

    # ── Queries ──────────────────────────────────────────────────────────

    def node_count(self) -> int:
        return len(self.visited_nodes)

    def node_fraction(self) -> float:
        return len(self.visited_nodes) / _NODE_TOTAL

    def stagnation(self, current_step: int) -> int:
        return current_step - self.last_new_node_step

    # ── Reporting ────────────────────────────────────────────────────────

    def _all_nodes(self) -> list[tuple[int, Optional[str]]]:
        max_occ = (1 << self.num_outputs) - 1
        nodes: list[tuple[int, Optional[str]]] = [(0, None)]
        for occ in range(1, max_occ + 1):
            for lvl in _SOC_LEVELS:
                nodes.append((occ, lvl))
        return nodes

    def _unvisited_top(self, limit: int = 20) -> list[dict]:
        visited_occs = [o for (o, _) in self.visited_nodes]
        out: list[dict] = []
        for occ, L in self._all_nodes():
            if (occ, L) in self.visited_nodes:
                continue
            # Hamming distance (occupancy bits) to the nearest visited node.
            if visited_occs:
                hd = min(bin(occ ^ vo).count("1") for vo in visited_occs)
            else:
                hd = bin(occ).count("1")
            out.append({
                "node": (occ, L),
                "occupancy_bits": format(occ, f"0{self.num_outputs}b"),
                "hamming_to_visited": hd,
                # Behavioural guess (not an error), keyed on Hamming distance.
                "guess": (
                    "same occupancy, unvisited SOC bucket" if hd == 0 else
                    "reachable next round (1–2 ports away)" if hd <= 2 else
                    "needs more concurrent ports than reached"
                ),
            })
            if len(out) >= limit:
                break
        return out

    def report(self) -> dict:
        """Coverage section of the §11 report as a structured dict."""
        L_dist: dict[str, int] = {}
        N_dist: dict[int, int] = {}
        for occ, L in self.visited_nodes:
            L_key = L if L is not None else "⊥"
            L_dist[L_key] = L_dist.get(L_key, 0) + 1
            n = bin(occ).count("1")
            N_dist[n] = N_dist.get(n, 0) + 1
        return {
            "nodes_visited": len(self.visited_nodes),
            "nodes_total": _NODE_TOTAL,
            "node_fraction": self.node_fraction(),
            "L_distribution": L_dist,
            "N_distribution": dict(sorted(N_dist.items())),
            "vehicle_classes_visited": len(self.visited_classes),
            "vehicle_classes_total": _CLASS_TOTAL,
            "edges_recorded": sum(self.edges.values()),
            "distinct_edges": len(self.edges),
            "unvisited_top20": self._unvisited_top(20),
        }

    # ── Cross-seed union dump (S5) ────────────────────────────────────────

    def dump_to_json(self, path: str, metadata: dict[str, Any]) -> None:
        """Write the visited (O, L) set + ``metadata`` as evcs-visited-v1 JSON.

        ``visited`` is a list of ``[occupancy_int, L_str]`` sorted by
        ``(occupancy, L_str)`` for diff-friendliness; the ⊥ empty-station L
        (stored internally as ``None``) serialises as the string ``"⊥"`` and
        round-trips back through ``union_coverage.py``. The parent directory is
        created if missing. Best-effort: a write failure prints a warning but
        never raises — a broken dump must not fail the test itself.
        """
        visited = sorted(
            [occ, (L if L is not None else "⊥")]
            for (occ, L) in self.visited_nodes
        )
        payload = {
            "schema": "evcs-visited-v1",
            "metadata": metadata,
            "universe_size": _NODE_TOTAL,
            "visited": visited,
        }
        try:
            dirname = os.path.dirname(path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as exc:  # pragma: no cover - defensive, must not raise
            print(f"  [WARN] dump_to_json failed for {path!r}: {exc}")
