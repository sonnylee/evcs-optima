"""TC-TOPO-01 to TC-TOPO-03: topology utility functions."""

import pytest
from simulation.utils.topology import is_ring, adjacent_pairs, ring_distance


# TC-TOPO-01: is_ring()
@pytest.mark.parametrize("num_mcus, expected", [
    (1, False),
    (2, False),
    (3, True),
    (4, True),
    (8, True),
])
def test_is_ring(num_mcus, expected):
    assert is_ring(num_mcus) is expected


# TC-TOPO-02: adjacent_pairs()
@pytest.mark.parametrize("num_mcus, expected", [
    (1, []),
    (2, [(0, 1)]),
    (3, [(0, 1), (1, 2), (2, 0)]),
    (4, [(0, 1), (1, 2), (2, 3), (3, 0)]),
])
def test_adjacent_pairs(num_mcus, expected):
    assert adjacent_pairs(num_mcus) == expected


# TC-TOPO-03: ring_distance()
@pytest.mark.parametrize("a, b, num_mcus, expected", [
    (0, 0, 3, 0),
    (0, 1, 3, 1),
    (0, 2, 3, 1),   # ring wrap shortcut
    (0, 3, 4, 1),   # ring wrap
    (0, 2, 4, 2),   # equidistant both ways
    (0, 1, 2, 1),   # linear
])
def test_ring_distance(a, b, num_mcus, expected):
    assert ring_distance(a, b, num_mcus) == expected
