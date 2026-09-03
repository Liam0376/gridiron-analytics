import pytest
from ffanalytics.conformal import qhat, interval, empirical_coverage

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


def test_empirical_coverage_synthetic_fixture():
    # Synthetic only — no live data. 80% is target, not guarantee.
    y_true = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
    preds = [11.0, 11.5, 14.2, 15.0, 19.0, 19.5, 22.5, 23.0, 27.0, 29.5]
    residuals = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5]
    positions = ["QB", "RB", "WR", "TE", "K", "QB", "RB", "WR", "TE", "K"]
    cov = empirical_coverage(y_true, preds, residuals, alpha=0.2, positions=positions)
    assert cov["n"] == 10
    assert cov["target"] == pytest.approx(0.8)
    assert 0.0 <= cov["overall"] <= 1.0
    assert set(cov["by_pos"].keys()) <= {"QB", "RB", "WR", "TE", "K"}
    for v in cov["by_pos"].values():
        assert 0.0 <= v <= 1.0


def test_empirical_coverage_monotonic_in_width():
    # Wider calibration residuals → wider intervals → coverage non-decreasing.
    y_true = [10.0, 12.0, 14.0, 16.0, 18.0]
    preds = [10.5, 12.5, 13.0, 17.0, 18.5]
    tight = [0.5, 0.6, 0.7, 0.8, 0.9]
    wide = [1.0, 3.0, 5.0, 8.0, 12.0]
    c_tight = empirical_coverage(y_true, preds, tight, alpha=0.2)["overall"]
    c_wide = empirical_coverage(y_true, preds, wide, alpha=0.2)["overall"]
    assert c_wide >= c_tight
    # Empty input returns None (no silent 0.0)
    empty = empirical_coverage([], [], tight, alpha=0.2)
    assert empty["overall"] is None
    assert empty["n"] == 0


def test_coverage_2025_artifact_measured():
    # Coverage numbers published to data/models/coverage_2025.json (measure-only, widths frozen).
    # Raw via empirical_coverage(), displayed via pos_factor*point_factor per-row (see stat_projector header).
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "models" / "coverage_2025.json"
    assert p.exists(), "coverage_2025.json missing — run empirical_coverage on 2025 holdout"
    d = json.loads(p.read_text())
    assert d["n_holdout_2025"] >= 2000  # full holdout n=5425, or documented 2000-row sample
    for key in ("raw", "displayed"):
        assert 0.0 <= d[key]["overall"] <= 1.0
        for v in d[key]["by_pos"].values():
            assert 0.0 <= v <= 1.0
    # Widths frozen — artifact must state measure-only
    assert "frozen" in d.get("note", "").lower() or "measure" in json.dumps(d).lower()