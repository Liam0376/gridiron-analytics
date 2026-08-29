# Spec: Play-by-Play Opportunity Features + XGBoost Ensemble

## Context

Current statistical model (`src/ffanalytics/stat_projector.py`) is backtested 2024-2025, N=10,356, weeks 4-18:

- **MAE=4.163, Corr=0.6918, Pairwise=77.7%** (stat_projector.py:5 header, backtest_final_results.json)
- Per-position: QB 7.08, RB 4.43, WR 4.42, TE 3.63
- Theoretical floor (optimistic): QB 6.7, RB 4.0 → gap ~0.5 pts remains

18 methods tested and rejected (header + AGENTS.md) — most notably opponent defense (rho=0.05-0.34, corr 0.690→0.687), EWMA, home/away, full Vegas scaling, rest. Only 5 factors survived: weighted-recent (5g@2x), TD regression 30%, usage trend 15%, damped Vegas, wind/cold.

Remaining signal class not yet used: **direct opportunity measures** (snap share, target share, rush share, red zone). Current features are outcome-based (yards/TDs) — they lag role changes. Play-by-play (PBP) via `nflreadpy.load_pbp` gives snap-level opportunity before it converts to fantasy points.

Goal: build ML layer that *adds* opportunity + Vegas + weather context via gradient-boosted trees, then ensemble with statistical model. Must be strictly better on **all** of MAE, corr, pairwise vs `MAE=4.163` baseline, time-series clean, and degrade gracefully without deps.

## Goals

- Add PBP-derived opportunity features that capture role before production.
- Train XGBoost regressor to predict `actual fantasy points` from projected stats + context + opportunity, using only past data (no leakage).
- Ensemble XGB + statistical model via validation MAE blend; integrate behind `use_ml=True` flag, keep stat model as zero-dep fallback.
- Expected lift 0.2-0.5 MAE / +2-5% corr if opportunity signal exists; else ship nothing (keep current model).

## Non-Goals

- No new paid service, no cloud training, no GPU requirement. Train locally on 3 seasons (<50k rows).
- No replacement of scoring layer (MAE=0.98) or conformal/decision layers — only stat projection input changes.
- No re-testing rejected factors (opponent defense, EWMA, home/away, etc.) — per `AGENTS.md: Tested and REJECTED`.
- No ESPN adapter, no multi-league, no betting logic.

## Data & Interfaces

### New PBP source

- **Adapter:** `src/ffanalytics/adapters/nflverse.py` → new `get_pbp_features(season, nfl_module=None) -> list[dict]` or dedicated `src/ffanalytics/adapters/pbp.py` (one file handles Polars boundary). Must return plain `list[dict]` — Polars never leaks (existing constraint).
- **Cache:** extend `nfl_cache/` with `pbp_2023.json`, `pbp_2024.json`, `pbp_2025.json` — aggregated per-player-per-week opportunity features (not raw plays). Reuse existing temp cache dir: `/private/tmp/claude-501/-Users-liam/.../nfl_cache/` for scratch, then copy to `data/nfl_cache/` or `nfl_cache/` under repo if persisting (decide in plan). Temp path is gitignored; plan must pick one persistent location.
- **Features per player-week to derive from PBP:**
  - `target_share` = team_targets ? player_targets / team_targets
  - `rush_share` = team_carries ? player_carries / team_carries
  - `snap_share` = if NGS snap counts available via PBP, else proxy via `play_count / team_plays`
  - `redzone_targets`, `redzone_carries`, `air_yards`, `air_yards_share`
  - `route_share` if available
  - All as season-to-date weighted averages (same RECENT_N=5@2x discipline) to avoid single-week noise

### Existing inputs reused

- Current stat projections per stat key (already in `project_player_stats`)
- Vegas: `implied_total`, `spread` from `build_game_context` (schedule)
- Weather: `wind`, `temp`, `is_dome` from schedule
- Recent trend slope, `games_played` (confidence proxy), `position` one-hot
- `team` for optional opponent-stub (but opponent defense stays rejected)

### Model I/O

- **Training rows:** one row per player-week (weeks 4-18, positions QB/RB/WR/TE/K), features as above + Vegas/weather/context. Target = `actual fantasy points` via `calculate_fantasy_points(..., SCORING)` (same SCORING dict from `projection.py`).
- **Split:** time-series only — train 2023-2024, validate 2025 (or rolling 2023→2024, 2023-2024→2025 CV). Never train on future weeks.
- **Inference:** `project_player_stats(..., use_ml=True)` → returns same `Dict[str,float]` per stat key *or* direct points — decide: easier is predict points directly, but stat-level preserves Vegas/weather damping. Spec: predict points directly from features (simpler, fewer error paths); stat-level ML is phase 2 if point-level fails.

## Model Design

### XGBoost regressor

- Library: `xgboost` + `scikit-learn` for `TimeSeriesSplit` and `mean_absolute_error`.
- Params start conservative: `n_estimators=500, max_depth=5, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, objective=reg:squarederror`, early_stopping on validation MAE.
- Position handling: one-hot `position_QB/RB/WR/TE/K` as features; or separate pickle per position if single model underfits QB variance (QB MAE 7.08 vs TE 3.63). Start single model, measure per-position MAE — split only if QB drags.

### Ensemble

- `final_pts = w * xgb_pts + (1-w) * stat_model_pts`
- `w` found by grid 0.0→1.0 step 0.05 minimizing validation MAE (2025). Report `w` in backtest JSON.
- Keep `stat_model_pts` as pure-math fallback when `xgboost` import fails.

## Integration

- **Flag:** `project_player_stats(..., use_ml: bool = False)` and `build_weekly_projections(..., use_ml: bool = False)`. Default `False` preserves current behavior and zero-dep install.
- **Dependency guard:** `try: import xgboost except ImportError: use_ml falls back to False with warning`. `projection.py` must call with `use_features=False` regardless (prediction-mode rule).
- **Artifacts:** `data/models/xgb_fantasy_v1.json` (XGB booster) + `data/models/xgb_meta.json` (feature list, w, val MAE, train seasons). Gitignore `data/models/*.json`? Decide in plan — likely commit `xgb_meta.json` but gitignore large booster if >5MB, or commit anyway (repo-local, no cloud).
- **No schema change:** no new DB tables for v1; PBP cache is file cache, not DB.

## Verification Gates

- **Gate 1 (no regression):** Backtest weeks 4-18, 2024-2025 combined vs baseline `MAE=4.163, corr=0.6918, pairwise=77.7%` — ensemble must beat **all three** (not just MAE). Run `backtest_final.py` and new `backtest_ml.py` head-to-head on same `nfl_cache` + PBP cache.
- **Gate 2 (time-series clean):** No future leakage — train rows only use `week < target_week` history. Manual audit of `build_weekly_projections` history slicing + `TimeSeriesSplit` n_splits.
- **Gate 3 (fallback):** `SLEEPER_LEAGUE_ID=test python -c "from ffanalytics.stat_projector import project_player_stats; print(project_player_stats([], 'WR'))"` works without `xgboost` installed (returns stat-model projection, no exception).
- **Gate 4 (no rejected retest):** `config.py FEATURES` diff shows no opponent-defense re-addition; grep `defense` in new code should be absent except in REJECTED comments.

## Risks

- PBP for 3 seasons is large (~300MB parquet) — `load_pbp` may OOM on 8GB Mac. Mitigate: aggregate per-week in PBP adapter, cache incrementally, or sample 2024 first.
- Theoretical gap only 0.5 pts — XGB may not beat stat model. Acceptable outcome: ship nothing, keep statistical model, document `xgb tested and REJECTED — evidence: val MAE 4.18 > 4.163`.
