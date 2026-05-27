"""End-to-end latency benchmark for ``POST /sessions/{id}/apply-and-generate``.

Complements ``test_web_session_engine_perf.py`` (single ``create()`` call,
P95 < 1 s) by measuring the *full request*: a multi-port Present→Target
transition fans out into a progressive-demand walk, each step settled via
``WebSessionEngine.create()`` inside ``step_planner`` (worst case
``_MAX_PROGRESSIVE_STEPS`` × ``_CONVERGE_TIMEOUT_TICKS`` plus settle passes).

SPEC-WEB-API §3.3 #3 budgets this path at P95 ≤ 5 s. Benchmark-marked, so it
is excluded from the default suite (``addopts = -m "not benchmark"``); run with:

    pytest services/evcs-api/tests/test_apply_and_generate_perf.py -m benchmark -s -v
"""
from __future__ import annotations

import statistics
import time
from typing import Dict, List

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.session_service import reset_store_for_tests

ITERATIONS = 20
P95_BUDGET_MS = 5000.0  # SPEC-WEB-API §3.3 #3


def _config() -> Dict:
    return {
        "rec_bd_count": 4,
        "rec_bds": [
            {"id": i + 1, "module_powers": [50, 75, 75, 50]} for i in range(4)
        ],
    }


def _car_ports() -> List[Dict]:
    """Realistic multi-port scenario: 3 ports arrive with distinct demand
    changes (incl. a 250 kW cross-MCU borrow) while the rest stay idle.
    All 8 priorities are set so FR-14 does not 422 on PrioritiesIncomplete.
    """
    targets = {1: 250, 3: 125, 5: 200}
    ports: List[Dict] = []
    for pid in range(1, 9):
        tgt = targets.get(pid, 0)
        ports.append(
            {
                "port_id": pid,
                "max_required": tgt,
                "present": 0,
                "target": tgt,
                "priority": pid,
            }
        )
    return ports


@pytest.mark.benchmark
def test_apply_and_generate_e2e_p95(capsys):
    reset_store_for_tests()
    client = TestClient(create_app())

    cfg = _config()
    ports = _car_ports()

    # Warm-up: first request pays import / module-init cost.
    r = client.post("/api/v1/sessions", json={"system_config": cfg, "car_ports": ports})
    assert r.status_code == 201, r.text
    warm_sid = r.json()["session_id"]
    r = client.post(f"/api/v1/sessions/{warm_sid}/apply-and-generate")
    assert r.status_code == 200, r.text
    assert r.json()["total_steps"] > 0, "scenario should produce control steps"

    durations_ms: List[float] = []
    for _ in range(ITERATIONS):
        # Fresh session each iteration so we time a cold Present→Target build.
        r = client.post(
            "/api/v1/sessions", json={"system_config": cfg, "car_ports": ports}
        )
        sid = r.json()["session_id"]

        t0 = time.perf_counter()
        resp = client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
        durations_ms.append((time.perf_counter() - t0) * 1000.0)

        assert resp.status_code == 200, resp.text

    durations_ms.sort()
    p50 = statistics.median(durations_ms)
    # quantiles(n=20) → 19 cut points; index 18 = 95th percentile.
    p95 = statistics.quantiles(durations_ms, n=20)[18]
    mx = max(durations_ms)

    with capsys.disabled():
        print()
        print(f"apply-and-generate e2e ({ITERATIONS} iters):")
        print(f"  P50={p50:.1f}ms  P95={p95:.1f}ms  max={mx:.1f}ms")
        print()

    assert p95 < P95_BUDGET_MS, (
        f"apply-and-generate P95 {p95:.1f} ms exceeds "
        f"{P95_BUDGET_MS:.0f} ms SPEC budget"
    )
