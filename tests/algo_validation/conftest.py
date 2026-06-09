"""Fixtures for the exploration harness (spec §7)."""
from __future__ import annotations

import os

import pytest

from simulation.environment.simulation_engine import SimulationEngine
from simulation.utils.config_loader import SimulationConfig
from tests.algo_validation.helpers.arrival_scheduler import ArrivalScheduler
from tests.algo_validation.helpers.coverage_tracker import CoverageTracker

NUM_MCUS = 4          # spec §16 validation layout → 8 outputs, 766-node space
# D-12 seed, overridable per-run via env var for multi-seed sweeps (S4). Unset
# → 12345 (the historical default), so the suite is unchanged by default.
SEED = int(os.environ.get("EVCS_SEED", "12345"))
# ε-greedy exploration rate (S4). Default 0.0 = pure greedy = byte-identical to
# pre-S4 behaviour (regression safety net); opt in with EVCS_EPSILON=0.2.
EPSILON = float(os.environ.get("EVCS_EPSILON", "0.0"))


@pytest.fixture
def empty_engine() -> SimulationEngine:
    """Fresh 4-MCU station, no initial vehicles (async actor path)."""
    return SimulationEngine(
        SimulationConfig(dt=1.0, t_end=1e9, num_mcus=NUM_MCUS),
        scenario_name="exploration",
    )


@pytest.fixture
def scheduler() -> ArrivalScheduler:
    return ArrivalScheduler(num_outputs=NUM_MCUS * 2, seed=SEED, epsilon=EPSILON)


@pytest.fixture
def tracker() -> CoverageTracker:
    return CoverageTracker(num_outputs=NUM_MCUS * 2)
