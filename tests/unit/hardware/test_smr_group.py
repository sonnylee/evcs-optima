"""TC-SMR-01 to TC-SMR-03: SMRGroup tests."""

from simulation.hardware.smr_group import SMRGroup


# TC-SMR-01: total_power_kw (2 SMRs = 50kW)
def test_total_power_2_smrs():
    group = SMRGroup("G0", num_smrs=2)
    assert group.total_power_kw == 50.0


# TC-SMR-02: SMR disabled lowers power
def test_smr_disabled_reduces_power():
    group = SMRGroup("G0", num_smrs=2)
    group.smrs[0].enabled = False
    assert group.total_power_kw == 25.0


# TC-SMR-03: get_status structure
def test_get_status_structure():
    group = SMRGroup("G0", num_smrs=2)
    status = group.get_status()
    assert "group_id" in status
    assert "total_power_kw" in status
    assert len(status["smrs"]) == 2


# Additional: step() is passthrough to SMRs
def test_step_passthrough():
    group = SMRGroup("G0", num_smrs=2)
    group.step(1.0)  # should not raise
    assert group.total_power_kw == 50.0


# Additional: 3-SMR group = 75kW
def test_total_power_3_smrs():
    group = SMRGroup("G1", num_smrs=3)
    assert group.total_power_kw == 75.0
