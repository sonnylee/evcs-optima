"""WebSessionEngine perf benchmark — Step F09.1.5.

Run only with the ``benchmark`` marker (excluded from default suite):

    pytest services/evcs-api/tests/test_web_session_engine_perf.py -m benchmark -s -v

Produces P50 / P95 / P99 / max latency for ``create() + to_visual_snapshot()``
across 6 scenarios × 100 iterations each. Numbers are echoed to stdout for
copy-paste into ``docs/SPIKE-FR09-REPORT.md`` and ``docs/SPEC-WEB-API.md``.
"""
from __future__ import annotations

import statistics
import time
from typing import List, Tuple

import pytest

from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.services.web_session_engine import WebSessionEngine


def _system() -> SystemConfig:
    return SystemConfig.model_validate(
        {
            "rec_bd_count": 4,
            "rec_bds": [{"id": i + 1, "module_powers": [50, 75, 75, 50]} for i in range(4)],
        }
    )


def _ports(specs: List[Tuple[int, int, int | None]]) -> List[CarPortInput]:
    return [
        CarPortInput.model_validate(
            {"port_id": pid, "max_required": mr, "present": 0, "target": 0, "priority": pr}
        )
        for pid, mr, pr in specs
    ]


def _scenario(overrides: List[Tuple[int, int, int | None]]) -> List[CarPortInput]:
    base = {pid: (pid, 0, None) for pid in range(1, 9)}
    for pid, mr, pr in overrides:
        base[pid] = (pid, mr, pr)
    return _ports(list(base.values()))


SCENARIOS: dict[str, List[CarPortInput]] = {
    "empty": _scenario([]),
    "single_125": _scenario([(1, 125, None)]),
    "single_250": _scenario([(1, 250, None)]),
    "two_local": _scenario([(1, 125, None), (2, 125, None)]),
    "two_cross_mcu": _scenario([(1, 350, None)]),
    "full_8_ports": _ports([(pid, 125, None) for pid in range(1, 9)]),
}

ITERATIONS = 100


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_perf_full_matrix(capsys):
    system = _system()
    rows: List[Tuple[str, float, float, float, float]] = []

    # Warm-up so first-call import / module init doesn't skew numbers.
    _ = await WebSessionEngine.create(system, SCENARIOS["empty"])

    for name, ports in SCENARIOS.items():
        durations_ms: List[float] = []
        for _ in range(ITERATIONS):
            t0 = time.perf_counter()
            engine = await WebSessionEngine.create(system, ports)
            engine.to_visual_snapshot()
            durations_ms.append((time.perf_counter() - t0) * 1000.0)

        durations_ms.sort()
        p50 = statistics.median(durations_ms)
        # `quantiles(n=20)` produces 19 cut points; index 18 = 95th percentile.
        p95 = statistics.quantiles(durations_ms, n=20)[18]
        # `quantiles(n=100)` produces 99 cut points; index 98 = 99th percentile.
        p99 = statistics.quantiles(durations_ms, n=100)[98]
        mx = max(durations_ms)
        rows.append((name, p50, p95, p99, mx))

    # Echo to stdout (need ``-s`` to see).
    with capsys.disabled():
        print()
        print(f"{'scenario':<18} {'P50':>10} {'P95':>10} {'P99':>10} {'max':>10}")
        print("-" * 62)
        for name, p50, p95, p99, mx in rows:
            print(f"{name:<18} {p50:>8.2f}ms {p95:>8.2f}ms {p99:>8.2f}ms {mx:>8.2f}ms")
        print()

    # Sanity guard — if any scenario blows past the 1 s SPEC budget, fail loudly.
    for name, _p50, p95, _p99, _mx in rows:
        assert p95 < 1000, f"scenario {name} P95 {p95:.1f} ms exceeds 1 s SPEC budget"
