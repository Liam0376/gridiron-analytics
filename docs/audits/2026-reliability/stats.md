# Mathematical / Statistical Reliability Audit

Date: 2026-09-15
Agent: Mathematical / Statistical Reliability

## Model Architecture

Production model: stat_projector.py (weighted-recent avg + TD regression + usage trend +
Vegas damping + weather). XGBoost REJECTED (data/ml/backtest_ml_results.json).

Freeze gate: MAE=4.563, Corr=0.648, Pairwise=74.1% (n=10,351, 2024-2025, weeks 4-18,
true scoring with K fg_* + 40+ bonuses).

## Findings

### S1: Coverage claims are honest but limited (Medium)

**2025 holdout (n=5425):** Calibration residuals from 2024 (n=5281), evaluated once on 2025.
Raw conformal coverage: 80.5% overall (target 80%). QB 58.1%, K 86.1%.
Displayed (heuristic scaling): 82.1% overall. QB 79.0%, K 58.6%.

Evidence: data/models/coverage_2025.json. Method documented in stat_projector.py header.
The "82.3% overall" mentioned in commit ab564d8 matches the displayed 82.1% (rounding).
The "QB 65.7% n=35" in the commit is from coverage_2026_live.json week 1 roster slice.

**2026 live (n=16, week 1 only):** 81.25% overall. QB 33.3% (n=3), WR 83.3% (n=6).
File correctly flags: "n=16 is SMALL SAMPLE, not statistically conclusive."

**Assessment:** The 2024->2025 holdout is honestly derived. The displayed interval scaling
breaks conformal guarantees (documented in conformal.py:1-10). QB undercoverage is the known
weak spot. The 2026 live number is too small to confirm or refute.

### S2: No leakage in backtest protocol (Clean)

stat_projector.py uses weeks < target_week filter (line 652) in same-season mode.
Cross-season mode uses full prior season (line 649). Both are true out-of-sample.

Checked: build_game_context uses schedule data (observed post-game temp/wind, documented
at stat_projector.py:537-543 as a known lookahead for backtest comparability).
Impact: "measured impact is small (weather corr +0.0004)." Documented, not hidden.

### S3: TD regression prior levels recalibrated correctly (Clean)

POS_TD_MEANS updated 2026-09-15 from xFP-implied rates. Evidence:
data/ml/backtest_opportunity_results.json. BASE-FROZEN paired-t t=42.4 (n=8049, 2025)
and t=16.1 (n=652, 2026 wk1). Both samples favor FROZEN. Shipped.

QB passing_tds 1.7 -> 0.83 (QFROZEN: t=14.5 on 2025, t=4.7 on 2026 wk1). Shipped.

### S4: Sample size for t-stat validity (Medium)

The backtest protocol uses paired-t tests across all player-weeks. With n=8049-10351,
central limit theorem applies and normality assumption is reasonable.

Position-level breakdowns (QB n=~700, K n=~300) are smaller but still adequate for
paired tests. The n=16 and n=35 2026 samples are too small for statistical conclusions.

### S5: Overfitting check (Clean)

XGBoost rejected with documented evidence (val 4.514 vs stat 4.474, fails OOS gate).
Stat-level XGBoost rejected (in-sample 2024 leakage documented). Ensemble rejected.
The production model has 5 factors, each contributing +0.001-0.002 correlation.
No sign of overfitting at this complexity level.

### S6: Interval width factors are frozen (Correct)

projection.py:POS_WIDTH_FACTORS derived from per-pos MAE / overall 4.16.
WIDTH_MIN=3.0, WIDTH_MAX=14.0. Documented as "heuristic, not calibrated."
The freeze prevents p-hacking through repeated width tuning.

### S7: Variance model is position-only, not player-specific (Low)

All QBs get the same 1.45x width factor. A volatile backup QB and a stable elite QB
get identical intervals. Player-specific volatility (trailing variance of residuals)
would improve coverage but requires per-player residual tracking.

Recommendation: Track per-player residuals in projection_snapshots table, but do NOT
use them for intervals until n>30 per player (avoid small-sample noise).
