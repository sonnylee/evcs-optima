"""Regression test for the opt-in ordered trajectory (coverage_tracker.py).

Two guarantees the trajectory feature must never break:

  1. **visited is byte-identical** — with no opt-in the dump is byte-for-byte
     what it was before the feature (no ``trajectory`` key, same key order),
     and even when opt-in adds the key the ``visited`` value is unchanged. The
     ε=0.0 cross-seed union regression depends on this.
  2. **set(trajectory nodes) == visited** — the ordered trajectory reuses the
     exact key written to ``visited_nodes`` (⊥ encoded as ``"⊥"``), so the
     de-duplicated trajectory is precisely the visited set.

Pure test-layer; drives ``CoverageTracker`` directly (no engine needed).
"""
from __future__ import annotations

import json

from tests.algo_validation.helpers.coverage_tracker import CoverageTracker
from tests.algo_validation.union_coverage import load_dump


def _populated() -> CoverageTracker:
    """A tracker driven like the harness: empty start, arrivals, a revisit,
    then back to empty (which resets L to ⊥)."""
    t = CoverageTracker(num_outputs=8)
    t.record(0, 0)                      # clean empty start → [0, 0, "⊥"]
    t.note_arrival("low"); t.record(1, 12)
    t.note_arrival("high"); t.record(3, 20)
    t.record(1, 25)                     # departure settle → revisit, kept
    t.record(0, 30)                     # empty again → L reset to ⊥
    return t


def test_first_record_is_clean_empty_start() -> None:
    t = _populated()
    assert t._trajectory[0] == [0, 0, "⊥"]


def test_trajectory_keeps_revisits_in_order() -> None:
    t = _populated()
    # 5 record() calls → 5 ordered entries, revisit included (not de-duped).
    assert t._trajectory == [
        [0, 0, "⊥"],
        [12, 1, "low"],
        [20, 3, "high"],
        [25, 1, "high"],
        [30, 0, "⊥"],
    ]


def test_trajectory_node_set_equals_visited() -> None:
    t = _populated()
    traj_nodes = {(occ, None if L == "⊥" else L) for _, occ, L in t._trajectory}
    assert traj_nodes == t.visited_nodes


def test_default_dump_is_byte_identical(tmp_path, monkeypatch) -> None:
    """No opt-in (param off, env unset) → no trajectory key, exact key order."""
    monkeypatch.delenv("EVCS_DUMP_TRAJECTORY", raising=False)
    t = _populated()
    path = tmp_path / "default.json"
    t.dump_to_json(str(path), metadata={"seed": 1})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "trajectory" not in data
    assert list(data.keys()) == ["schema", "metadata", "universe_size", "visited"]


def test_optin_preserves_visited_and_adds_trajectory(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("EVCS_DUMP_TRAJECTORY", raising=False)
    t = _populated()
    base = tmp_path / "base.json"
    optin = tmp_path / "optin.json"
    t.dump_to_json(str(base), metadata={"seed": 1})
    t.dump_to_json(str(optin), metadata={"seed": 1}, include_trajectory=True)

    d_base = json.loads(base.read_text(encoding="utf-8"))
    d_optin = json.loads(optin.read_text(encoding="utf-8"))
    # visited byte-identical (value unchanged under opt-in).
    assert d_optin["visited"] == d_base["visited"]
    traj = d_optin["trajectory"]
    assert traj["schema"] == "evcs-trajectory-v1"
    assert traj["fields"] == ["step", "occ", "L"]
    assert traj["records"] == t._trajectory


def test_env_var_enables_trajectory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EVCS_DUMP_TRAJECTORY", "1")
    t = _populated()
    path = tmp_path / "env.json"
    t.dump_to_json(str(path), metadata={"seed": 1})  # no param → env gate only
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["trajectory"]["schema"] == "evcs-trajectory-v1"


def test_union_coverage_ignores_trajectory_key(tmp_path, monkeypatch) -> None:
    """The opt-in dump still loads cleanly through union_coverage (unknown key
    ignored, visited round-trips)."""
    monkeypatch.delenv("EVCS_DUMP_TRAJECTORY", raising=False)
    t = _populated()
    path = tmp_path / "optin.json"
    t.dump_to_json(str(path), metadata={"seed": 1}, include_trajectory=True)
    loaded = load_dump(str(path))  # must not raise on the extra key
    expected = {(occ, "⊥" if L is None else L) for occ, L in t.visited_nodes}
    assert loaded["visited"] == expected
