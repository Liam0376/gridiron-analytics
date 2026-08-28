import pytest
from ffanalytics.conformal import qhat, interval

def test_qhat_all_zero_residuals_is_zero():
    assert qhat([0.0, 0.0, 0.0], alpha=0.2) == pytest.approx(0.0)

def test_qhat_increases_with_residual_spread():
    tight = qhat([1.0, 1.0, 1.0, 1.0, 1.0], alpha=0.2)
    wide = qhat([1.0, 2.0, 5.0, 8.0, 10.0], alpha=0.2)
    assert wide > tight

def test_qhat_empty_residuals_raises():
    with pytest.raises(ValueError, match="residuals"):
        qhat([], alpha=0.2)

def test_interval_is_symmetric_around_point_estimate():
    lo, hi = interval(14.2, [1.0, 2.0, 3.0, 4.0], alpha=0.2)
    width = qhat([1.0, 2.0, 3.0, 4.0], alpha=0.2)
    assert lo == pytest.approx(14.2 - width)
    assert hi == pytest.approx(14.2 + width)