"""Split conformal prediction for calibrated confidence intervals —
adapted from ~/projects/sports-analytics' core/math.py `conformal_qhat`
pattern. Turns a bare point projection into a calibrated interval, per
design spec's start/sit "confident vs. it's close" distinction."""

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