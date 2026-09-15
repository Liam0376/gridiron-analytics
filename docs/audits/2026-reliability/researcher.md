# Projection Measurement Researcher -- Reliability Audit 2026-09-15

## How professionals measure fantasy football projection accuracy

### 1. FantasyPros In-Season Accuracy (rank-slot error)

**What it measures:** Expert weekly ranking quality via "Accuracy Gap" -- the difference between projected points (derived from historical production at the expert's assigned rank slot) and actual points.

**Computation:** Snapshot expert rankings before Thursday/Sunday games. Assign projected point value from the historical mean production at that rank slot. Gap = |projected - actual|. Aggregate weekly gaps, z-score normalize, drop worst week after Week 8. Overall = QB + RB + WR + TE combined.

**Player pool:** Top N by ECR plus top N by actual (position-specific: WR top 50, RB top 40, TE/K/DST top 15). Unranked consensus players get last_rank+1. Surprise performers get max(ECR+1, expert_last+1).

**DNP/injury handling:** Injured players ranked by an expert but who score poorly are only penalized when the prediction "performs notably worse than average." No explicit exclusion of DNP/zero-score players from the evaluation pool.

**Scoring format:** Half PPR. Week 18 excluded.

**Source:** [FantasyPros In-Season Accuracy Methodology](https://www.fantasypros.com/about/faq/football-inseason-accuracy-methodology/)

**$0 feasibility:** Yes. Rankings data available free from FantasyPros ECR or nflverse free ECR feed (already ingested by this repo). Actual points computed locally.

**Gap vs this repo:** This repo tracks MAE on point projections, not rank-slot accuracy gap. FantasyPros' method is rank-based, not point-based. Both are useful; rank accuracy catches cases where point MAE is low but ordering is wrong.

---

### 2. MAE (Mean Absolute Error) -- industry standard

**What it measures:** Average absolute deviation between projected and actual fantasy points per player-week.

**Computation:** MAE = (1/n) * sum(|projected_i - actual_i|)

**Benchmarks (weekly, PPR, professional sources, 2015-2025 via fantasyfootballanalytics.net):**

| Position | Best Weekly MAE | Typical Range |
|----------|----------------|---------------|
| QB | ~5.5-7.0 | 6-9 |
| RB | ~5.0-5.2 | 5.0-6.5 |
| WR | ~4.8-5.0 | 4.8-5.5 |
| TE | ~3.5-4.0 | 3.5-5.0 |

Season-level MAE (sum of weekly points): QB 61, RB 52, WR 40, TE 31 (best sources).

**Source:** [FFA 12-Season Analysis](https://fantasyfootballanalytics.net/2026/08/we-analyzed-12-seasons-of-fantasy-football-projections-heres-what-we-found.html), [Which Projections Are Most Accurate](https://fantasyfootballanalytics.net/which-projections-are-most-accurate)

**$0 feasibility:** Yes. Computed locally from projections and actual scores.

**Gap vs this repo:** This repo reports combined MAE 4.563 (all positions, weeks 4-18). No per-position weekly MAE breakdown tracked as a recurring metric. Should add.

---

### 3. R-squared / Correlation

**What it measures:** How much variance in actual performance is explained by projections. R-squared for regression; Pearson/Spearman for rank correlation.

**Benchmarks (professional sources):**

| Position | R-squared Range |
|----------|----------------|
| QB | 7-15% |
| RB | 20-28% |
| WR | 14-19% |
| TE | 16-26% |

Spearman rank correlation for weekly rankings: 0.5-0.7 typical for skill positions.

**Source:** [FFA 12-Season Analysis](https://fantasyfootballanalytics.net/2026/08/we-analyzed-12-seasons-of-fantasy-football-projections-heres-what-we-found.html), [Fantasy Rankings Authority](https://fantasyrankingsauthority.com/fantasy-rankings-accuracy-and-evaluation/)

**$0 feasibility:** Yes. scipy.stats.spearmanr is in the standard scientific stack (already available via numpy which is a dependency of polars/nflreadpy).

**Gap vs this repo:** This repo reports Corr=0.648 (Pearson) combined. No Spearman rank correlation tracked. No per-position breakdown. Should add both.

---

### 4. Mean Error (Bias)

**What it measures:** Directional bias (positive = over-projection, negative = under-projection).

**Computation:** ME = (1/n) * sum(projected_i - actual_i)

**Benchmarks:** Professional sources show systematic over-optimism averaging +21.6 season points across positions. QB worst at +46.5 points recently. Calibration slopes: QB 0.67, TE 0.72, RB 0.79, WR 0.85 (1.0 = perfect calibration; <1 means exaggerated spread -- top players overprojected, bottom players approximately correct).

**Source:** [FFA 12-Season Analysis](https://fantasyfootballanalytics.net/2026/08/we-analyzed-12-seasons-of-fantasy-football-projections-heres-what-we-found.html)

**$0 feasibility:** Yes, trivial to compute.

**Gap vs this repo:** Not tracked as a recurring metric. Should add weekly ME and calibration slope.

---

### 5. Pairwise Accuracy (start/sit decision proxy)

**What it measures:** Given two players at the same position, how often does the projection correctly rank the higher scorer above the lower scorer?

**Computation:** For all pairs (i, j) where actual_i > actual_j within a position, check if projected_i > projected_j. Pairwise % = correct / total pairs.

**Benchmarks:** This repo's 74.1% pairwise is the primary decision-quality metric. No widely published professional benchmark exists for this exact metric, but it maps to Kendall's tau (concordance probability). Random = 50%. Expert consensus typically achieves 65-75% depending on position and sample.

**$0 feasibility:** Yes. Already computed in this repo's backtest.

**Gap vs this repo:** Already tracked as combined 74.1%. Should add per-position breakdown.

---

### 6. Prediction Interval Coverage (PICP)

**What it measures:** Fraction of actual outcomes falling within the stated prediction interval.

**Computation:** PICP = count(lower_i <= actual_i <= upper_i) / n. Target: 80% for an 80% interval.

**Related metrics:**
- **CRPS (Continuous Ranked Probability Score):** Penalizes both miscalibration and width. CRPS = integral of squared CDF difference between forecast and observation. Lower is better. Rewards sharp, well-calibrated intervals.
- **Pinball loss:** Per-quantile scoring that penalizes asymmetrically based on whether actual falls above or below the quantile.
- **Winkler score:** Combines coverage and interval width -- rewards narrow intervals that still cover.

**Source:** [CRPS Guide](https://towardsdatascience.com/essential-guide-to-continuous-ranked-probability-score-crps-for-forecasting-ac0a55dcb30d/), [Beyond Pinball Loss](https://arxiv.org/pdf/2011.09588)

**$0 feasibility:** Yes. CRPS/pinball computable from point estimate + width + actual. No external data needed. scipy not required; closed-form for Gaussian assumption or empirical via sorted residuals.

**Gap vs this repo:** This repo tracks PICP (82.1% displayed overall, 2025 holdout). Does not track CRPS, pinball loss, or Winkler score. Should add CRPS as the single best probabilistic accuracy metric (it subsumes both calibration and sharpness). PICP alone can be gamed by making intervals infinitely wide.

---

### 7. Beat-the-Consensus Test

**What it measures:** Whether this model's projections outperform the consensus (FantasyPros ECR or Sleeper market) on any metric.

**Computation:** Paired comparison on the same player-week universe. For each player-week, compute error for model vs consensus. Paired t-test or Wilcoxon signed-rank on the difference. Report: mean difference, t-stat, p-value, and 95% CI.

**Source:** The FFA analysis confirms aggregation beats individual sources ~69% of the time. Beating the consensus is the standard the industry uses.

**$0 feasibility:** Yes. This repo already fetches FantasyPros ECR and Sleeper projections. Comparing model vs consensus MAE is a paired t-test.

**Gap vs this repo:** Not computed. The comparison module builds model-vs-market rows but never computes a head-to-head accuracy score. Should add.

---

## Recommended Scorecard

Computed weekly after each game slate resolves, run as `scripts/scorecard.py`:

| Metric | Scope | Baseline | How |
|--------|-------|----------|-----|
| MAE | Overall + per-position | FantasyPros consensus MAE | |projected - actual| per player-week |
| ME (Bias) | Overall + per-position | 0.0 (unbiased) | mean(projected - actual) |
| Spearman rho | Per-position | 0.5-0.7 (pro sources) | scipy.stats.spearmanr or manual |
| Pairwise % | Per-position | 65-75% (pro consensus) | Concordant pairs / total pairs |
| PICP | Overall + per-position | 80% target | count(in-interval) / n |
| CRPS | Overall + per-position | Lower is better (no universal benchmark) | Closed-form for empirical CDF |
| Beat-consensus | Overall | Model MAE < Consensus MAE | Paired t-test on |model_err| - |consensus_err| |
| Calibration slope | Per-position | 1.0 (perfect) | OLS actual ~ projected, report slope |
| n (sample size) | Per-position | Report alongside all metrics | Required for significance |

### Script design (`scripts/scorecard.py`)

```
Input: data/fantasy.db (player_stats week=0 blob has projected_points; 
       sleeper_matchups has actuals via Sleeper; 
       market_consensus has consensus projections)
       
For each completed week:
  1. Load projected_points from the player_stats blob for that week
  2. Load actual points from Sleeper matchups or nflverse actuals
  3. Join on player_id (gsis via sleeper_xwalk)
  4. Compute: MAE, ME, Spearman, Pairwise, PICP, CRPS per position
  5. Load consensus projections from market_consensus
  6. Compute beat-consensus paired test
  7. Output JSON to data/models/scorecard_<season>_<week>.json
  8. Print summary table
```

Dependency: numpy (already installed via polars/nflreadpy chain). No new deps needed.

---

## Sources

- [FantasyPros In-Season Accuracy Methodology](https://www.fantasypros.com/about/faq/football-inseason-accuracy-methodology/)
- [FantasyPros Draft Accuracy Methodology](https://www.fantasypros.com/about/faq/football-draft-accuracy-methodology/)
- [FFA: 12 Seasons of Projections Analysis](https://fantasyfootballanalytics.net/2026/08/we-analyzed-12-seasons-of-fantasy-football-projections-heres-what-we-found.html)
- [FFA: Which Projections Are Most Accurate](https://fantasyfootballanalytics.net/which-projections-are-most-accurate)
- [Fantasy Rankings Authority: Accuracy Evaluation](https://fantasyrankingsauthority.com/fantasy-rankings-accuracy-and-evaluation/)
- [CRPS Guide (Towards Data Science)](https://towardsdatascience.com/essential-guide-to-continuous-ranked-probability-score-crps-for-forecasting-ac0a55dcb30d/)
- [Beyond Pinball Loss (arXiv)](https://arxiv.org/pdf/2011.09588)
- [CRPS Explanation (Medium)](https://medium.com/@mohsenim/time-series-forecasting-continuous-ranked-probability-score-crps-ff5b8383d0e1)
