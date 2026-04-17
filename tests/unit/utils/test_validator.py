"""TC-VAL-01 to TC-VAL-03: Validator tests."""

import pytest
from simulation.hardware.charging_station import ChargingStation
from simulation.log.relay_event_log import RelayEventLog
from simulation.utils.validator import Validator


def _make_validator(num_mcus=3):
    el = RelayEventLog()
    station = ChargingStation(mcu_id=0, event_log=el, num_mcus=num_mcus)
    station.initialize(dt_index=0)
    return Validator(station), station


# TC-VAL-01: no violations initially
def test_no_violations():
    v, station = _make_validator(3)
    v.check(0)
    assert v.has_failures() is False


# TC-VAL-02: multiple-owner conflict triggers violations_log
def test_multiple_owner_violation():
    v, station = _make_validator(3)
    ma = station.module_assignment
    # Manually set G5 owned by both O0 and O1
    ma._matrix[0][5] = 1
    ma._matrix[1][5] = 1

    v.check(1)
    assert len(v.violations_log) > 0


# TC-VAL-03: boundary_check records each neighbor pair
def test_boundary_check_records_pairs():
    v, station = _make_validator(3)
    entries = v.check(5)
    # 3-MCU ring: pairs are (0,1), (1,2), (2,0) → 3 entries
    assert len(entries) == 3
    pairs = [e["mcu_pair"] for e in entries]
    assert [0, 1] in pairs
    assert [1, 2] in pairs
    assert [2, 0] in pairs


def test_summary():
    v, station = _make_validator(3)
    v.check(0)
    s = v.summary()
    assert s["total_boundary_checks"] == 3
    assert s["inconsistent"] == 0
    assert s["station_violations"] == 0


def test_single_mcu_no_boundary():
    v, station = _make_validator(1)
    entries = v.check(0)
    assert len(entries) == 0
    assert v.has_failures() is False
