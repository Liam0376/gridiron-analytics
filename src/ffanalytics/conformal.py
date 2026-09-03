"""Split conformal prediction — base width computation only. The raw qhat
gives a formally calibrated interval (Vovk et al. 2005), but projection.py
scales it by position and point-magnitude factors, which breaks the coverage
guarantee. The displayed intervals are heuristic, not calibrated.

80% is a TARGET, not a guarantee: empirical coverage must be measured with
empirical_coverage() below on holdout data (expect <80% after heuristic
scaling; do not claim calibration in UI/docs). Interval widths are frozen
for display stability — this module only adds measurement, never retunes
widths."""

import math


def qhat(residuals: list[float], alpha: float = 0.2) -> float:
    if not residuals:
        raise ValueError("residuals must be non-empty to compute qhat")
    abs_residuals = sorted(abs(r) for r in residuals)
    n = len(abs_residuals)
    # standard split-conformal finite-sample correction
    rank = math.ceil((n + 1) * (1 - alpha))
    rank = min(rank, n)
    return abs_residuals[rank - 1]


def interval(point_estimate: float, residuals: list[float], alpha: float = 0.2) -> tuple[float, float]:
    width = qhat(residuals, alpha=alpha)
    return (point_estimate - width, point_estimate + width)


def empirical_coverage(
    y_true: list[float],
    point_estimates: list[float],
    residuals: list[float],
    alpha: float = 0.2,
    positions: list[str] | None = None,
) -> dict:
    """Measure empirical coverage P(y in interval) overall and by position.

    Uses the RAW conformal interval (qhat width, no projection.py heuristic
    scaling) so the number is an honest calibration check. Displayed UI
    intervals are wider/narrower by position/magnitude and will differ —
    this helper deliberately does not reproduce that scaling (widths frozen).

    Args:
        y_true: actual fantasy points per player-week.
        point_estimates: predicted points aligned with y_true.
        residuals: calibration residuals used for qhat (must be non-empty).
        alpha: miscoverage level (0.2 → 80% target, not guarantee).
        positions: optional position label per row (QB/RB/WR/TE/K) for by-pos
            breakdown; if omitted, only overall is returned.

    Returns:
        {"overall": float, "by_pos": {pos: float}, "n": int,
         "target": 1-alpha, "alpha": alpha}
        Coverage is None when n==0 (no silent 0.0).
    """
    n = len(y_true)
    if n == 0 or len(point_estimates) != n:
        return {
            "overall": None,
            "by_pos": {},
            "n": 0,
            "target": 1.0 - alpha,
            "alpha": alpha,
        }
    width = qhat(residuals, alpha=alpha)
    hits = [
        1 if (pred - width) <= actual <= (pred + width) else 0
        for actual, pred in zip(y_true, point_estimates)
    ]
    overall = sum(hits) / n if n else None
    by_pos: dict = {}
    if positions and len(positions) == n:
        from collections import defaultdict

        buckets: dict = defaultdict(list)
        for h, pos in zip(hits, positions):
            buckets[str(pos).upper()].append(h)
        for pos, vals in buckets.items():
            by_pos[pos] = sum(vals) / len(vals) if vals else None
    return {
        "overall": overall,
        "by_pos": by_pos,
        "n": n,
        "target": 1.0 - alpha,
        "alpha": alpha,
    }