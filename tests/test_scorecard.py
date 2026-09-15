"""Tests for scripts/scorecard.py metric functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from scorecard import compute_metrics, _spearman, _pairwise, _picp, _crps_gaussian


def test_spearman_perfect():
    assert _spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0


def test_spearman_inverse():
    r = _spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
    assert r == -1.0


def test_spearman_too_few():
    assert _spearman([1, 2], [3, 4]) is None


def test_pairwise_perfect():
    assert _pairwise([1, 2, 3], [1, 2, 3]) == 1.0


def test_pairwise_inverse():
    assert _pairwise([3, 2, 1], [1, 2, 3]) == 0.0


def test_pairwise_too_few():
    assert _pairwise([1], [1]) is None


def test_picp_all_covered():
    assert _picp([10.0, 20.0], [11.0, 19.0], [5.0, 5.0]) == 1.0


def test_picp_none_covered():
    assert _picp([10.0, 20.0], [20.0, 10.0], [1.0, 1.0]) == 0.0


def test_crps_gaussian_zero_sigma():
    assert _crps_gaussian(10.0, 0.0, 12.0) == 2.0


def test_crps_gaussian_positive():
    c = _crps_gaussian(10.0, 5.0, 10.0)
    assert 0 < c < 5


def test_compute_metrics_empty():
    assert compute_metrics([]) == {"n": 0}


def test_compute_metrics_basic():
    pairs = [(10.0, 12.0), (15.0, 14.0), (20.0, 18.0)]
    m = compute_metrics(pairs)
    assert m["n"] == 3
    assert m["mae"] > 0
    assert m["me"] is not None
    assert m["spearman"] == 1.0
    assert m["pairwise"] == 1.0


def test_compute_metrics_with_widths():
    pairs = [(10.0, 11.0), (20.0, 19.0)]
    widths = [5.0, 5.0]
    m = compute_metrics(pairs, widths=widths)
    assert m["picp"] == 1.0
    assert "crps" in m
