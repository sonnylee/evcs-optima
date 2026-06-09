"""``ArrivalScheduler`` — coverage-directed greedy arrival picker (spec §3.3).

Each call observes the current occupancy and returns either an ``Arrive``
(output index + SOC bucket) or ``None``:

  - ``None`` when the station is full (every output occupied) → the main loop
    idles and waits for a system-driven departure (the only way O shrinks).
  - ``None`` on the periodic settle beat: every ``idle_every`` (K=5, D-11)
    arrivals the next pick is skipped so the system can sediment.
  - otherwise an ``Arrive`` chosen greedily to reach an *unvisited* node;
    ties broken by a seeded RNG (D-12, seed 12345) for reproducibility.

The scheduler never drives departures (spec §3.1: depart is system-only).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

_SOC_LEVELS = ("low", "mid", "high")


@dataclass(frozen=True)
class Arrive:
    output_idx: int
    soc_level: str


class ArrivalScheduler:
    def __init__(
        self,
        num_outputs: int = 8,
        seed: int = 12345,
        idle_every: int = 5,
        epsilon: float = 0.0,
    ) -> None:
        self.num_outputs = num_outputs
        self.idle_every = idle_every
        # S4: ε-greedy exploration rate. 0.0 = pure greedy (default); the
        # short-circuit in ``choose`` keeps the greedy path byte-identical.
        self.epsilon = epsilon
        self._rng = random.Random(seed)
        self._since_idle = 0

    def _random_legal_arrival(self, occupancy: int) -> Optional[Arrive]:
        """A uniformly random legal arrival (S4 ε-greedy branch).

        Picks an unoccupied output and a random SOC bucket — the scheduler's
        full choice space (``Arrive`` is (output, soc); demand/``max_kw`` is set
        downstream by the harness, not here, and is not part of the coverage
        node key). Returns ``None`` when the station is full so the caller falls
        back to the greedy path.
        """
        empty = [i for i in range(self.num_outputs) if not (occupancy >> i) & 1]
        if not empty:
            return None
        return Arrive(self._rng.choice(empty), self._rng.choice(_SOC_LEVELS))

    def choose(self, occupancy: int, tracker) -> Optional[Arrive]:
        # S4 ε-greedy: with probability ε pick a random legal arrival to break
        # out of greedy local optima (stagnation). The ``self.epsilon > 0.0``
        # guard short-circuits BEFORE any ``self._rng`` draw, so when ε=0.0 the
        # RNG stream — and the greedy path below — is byte-identical to pre-S4.
        # A random branch that finds no legal arrival (full station) falls
        # through to the greedy path, which handles it.
        if self.epsilon > 0.0 and self._rng.random() < self.epsilon:
            result = self._random_legal_arrival(occupancy)
            if result is not None:
                return result

        empty = [i for i in range(self.num_outputs) if not (occupancy >> i) & 1]
        if not empty:
            return None  # station full → idle, wait for a departure

        # Periodic settle beat (D-11): every K successful arrivals, skip one.
        if self._since_idle >= self.idle_every:
            self._since_idle = 0
            return None

        # Greedy: prefer (output, SOC) that lands on an as-yet-unvisited node.
        unvisited: list[Arrive] = []
        for i in empty:
            for lvl in _SOC_LEVELS:
                new_occ = occupancy | (1 << i)
                if (new_occ, lvl) not in tracker.visited_nodes:
                    unvisited.append(Arrive(i, lvl))
        pool = unvisited if unvisited else [
            Arrive(i, lvl) for i in empty for lvl in _SOC_LEVELS
        ]
        choice = self._rng.choice(pool)
        self._since_idle += 1
        return choice
