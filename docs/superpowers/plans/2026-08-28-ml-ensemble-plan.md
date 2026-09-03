# Plan: Play-by-Play + XGBoost Ensemble (behind `use_ml` flag)

> For agentic workers: use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task-by-task. Checkboxes track progress. **Stop for user confirmation after Task 2** (spec + install gate) before writing model code, per `CLAUDE.md: Process`.

**Goal:** Add opportunity features (target/rush share, red zone, air yards) from nflverse PBP, train time-series-clean XGBoost to predict `actual fantasy points`, ensemble with statistical model (`MAE=4.163` baseline), keep only if it beats MAE/corr/pairwise head-to-head. Zero-dep fallback stays.

**Spec:** `docs/superpowers/specs/2026-08-28-ml-ensemble-spec.md`

**Constraints:** $0, local-only, 127.0.0.1, no cloud/GPU, never re-test REJECTED factors (opponent defense etc.), `src/ffanalytics/adapters/nflverse.py` is only Polars boundary, `projection.py:use_features=False` for prediction.

---

### Task 1: Lock research & confirm cache

**Files:** none (read-only)

- [ ] **Step 1:** Re-run `SLEEPER_LEAGUE_ID=1397736035240173568 /opt/homebrew/bin/python3 /private/tmp/claude-501/.../scratchpad/backtest_final.py` to reconfirm `MAE=4.163, corr=0.6918, pairwise=77.7%` on current `stat_projector.py`.
- [ ] **Step 2:** Inspect `nfl_cache/stats_*.json` keys vs `stat_projector.py:QB_STATS/SKILL_STATS` mapping (`team` not `recent_team`, keys `passing_yards` etc.) and `schedule_*.json` Vegas/weather fields (`total_line`, `spread_line`, `temp`, `wind`, `roof`).
- [ ] **Step 3:** Probe `nflreadpy.load_pbp(seasons=[2024])` single-season shape: list columns, row count, `play_type`, `receiver_player_id`, `rusher_player_id`, `air_yards`, `yardline_100`, `posteam`. Confirm `player_id` join key matches `stats_*.json` `player_id` (Sleeper nflverse ID, e.g. `4046`). Record findings in `docs/superpowers/plans/2026-08-28-ml-ensemble-progress.md`.

**Commit:** none (research only).

---

### Task 2: Dependency gate (ask permission)

**Files:** `pyproject.toml`, `requirements.txt`

- [ ] **Step 1:** Draft diff (do not apply yet):
  ```toml
  [project.dependencies]
  # existing + optional:
  # "xgboost>=2.0", "scikit-learn>=1.4", "numpy>=1.26"  — local only, no paid, ~50MB
  ```
- [ ] **Step 2:** Ask user: "`/opt/homebrew/bin/pip3 install xgboost scikit-learn numpy --break-system-packages` — ~50MB, local only, no tokens/cards. Install? (also `pip install -e .` to sync). Past denials noted — propose `--break-system-packages` explicitly."

- [ ] **Step 3:** On `yes`: install, `python -c "import xgboost, sklearn; print(xgboost.__version__)"`, update `pyproject.toml` + `requirements.txt`, `git commit -m "chore: add xgboost/sklearn/numpy (local ML, optional behind use_ml flag)"`. On `no`: stop, leave statistical model as best, document rejection.

**Verification:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` still 51 passed (ML deps don't break import — guarded).

---

### Task 3: PBP feature cache

**Files:** `src/ffanalytics/adapters/pbp.py` (new) or extend `nflverse.py`, `data/nfl_cache/pbp_*.json` (or keep temp), `tests/adapters/test_pbp.py`

- [ ] **Step 1:** Write failing test `tests/adapters/test_pbp.py`:
  ```python
  def test_pbp_features_shape():
      from ffanalytics.adapters import pbp
      rows = pbp.get_pbp_features(2024, nfl_module=FakePbp)  # FakePolarsFrame with 10 plays
      assert isinstance(rows, list) and isinstance(rows[0], dict)
      assert {"player_id","week","target_share","rush_share","air_yards"} <= set(rows[0])
  ```
- [ ] **Step 2:** Implement `src/ffanalytics/adapters/pbp.py:get_pbp_features(season, nfl_module=None) -> list[dict]` — only file touching `load_pbp`, converts `frame.to_dicts()` to plain dicts, aggregates per `(player_id, week)` → opportunity shares. Handle `team_targets`/`team_carries` zero division, dome `temp=None`.
- [ ] **Step 3:** Add caching: if `data/nfl_cache/pbp_2024.json` exists, load; else call nflreadpy, aggregate, write cache (atomic `tmp`→`final`). Keep scratch path as primary for backtests to avoid network.
- [ ] **Step 4:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/adapters/test_pbp.py -v` PASS. `python -c "from ffanalytics.adapters.pbp import get_pbp_features; print(len(get_pbp_features(2024, nfl_module=Fake)))"` spot-check.
- [ ] **Step 5:** Commit: `feat: PBP opportunity adapter (target/rush share, air yards, red zone) with plain-dict boundary`

---

### Task 4: Feature engineering + training data

**Files:** `src/ffanalytics/ml/__init__.py`, `src/ffanalytics/ml/features.py`, `tests/test_ml_features.py`

- [ ] **Step 1:** Write failing test for `ml/features.py:build_training_rows(season, week, player_history, pbp_cache, schedule) -> dict` returning row with keys: `target_share_wavg`, `rush_share_wavg`, `redzone_targets_wavg`, `air_yards_wavg`, `implied_total`, `spread`, `wind`, `temp`, `is_dome`, `games_played`, `position_QB/...`, plus projected stat features (`pass_yd_proj`, `rec_yd_proj`, etc.) from `stat_projector` pipeline.
- [ ] **Step 2:** Implement weighted averaging for PBP shares (same `RECENT_N=5@2x` as stats) to avoid single-week noise. Normalize `target_share` ∈[0,1], `rush_share` ∈[0,1].
- [ ] **Step 3:** Write script `scripts/build_ml_dataset.py` (not committed as prod code) to dump `data/ml/train_2023_2024.jsonl` + `val_2025.jsonl` — one JSON per row, `target=actual_pts`. Verify no leakage: `assert max(train_week) < min(val_week)` per player.
- [ ] **Step 4:** `pytest tests/test_ml_features.py -v` PASS.

---

### Task 5: XGBoost training

**Files:** `src/ffanalytics/ml/train.py`, `data/models/xgb_fantasy_v1.json`, `data/models/xgb_meta.json`

- [ ] **Step 1:** Write `train.py` CLI: `python -m ffanalytics.ml.train --train data/ml/train_2023_2024.jsonl --val data/ml/val_2025.jsonl --out data/models/xgb_fantasy_v1.json`
  Params: `n_estimators=500, max_depth=5, lr=0.03, subsample=0.8, colsample=0.8, reg_lambda=1.0, early_stopping_rounds=30` on val MAE via `sklearn.model_selection.TimeSeriesSplit`.
- [ ] **Step 2:** Train; log `val MAE`, `val corr`, feature importance (`gain`). If val MAE >4.163, stop — document `xgb tested and REJECTED` in meta, do not proceed to ensemble.
- [ ] **Step 3:** Write `xgb_meta.json`: `{features:[...], train_seasons:[2023,2024], val_season:2025, val_mae, val_corr, params, git_sha}`.

---

### Task 6: Ensemble + head-to-head backtest

**Files:** `scripts/backtest_ml.py`, `data/ml/backtest_ml_results.json`

- [ ] **Step 1:** Write `backtest_ml.py` mirroring `backtest_final.py` but for each week/player compute `stat_pts` (existing pipeline) + `xgb_pts` (model) + `ensemble = w*xgb + (1-w)*stat`, grid `w=0..1 step 0.05` minimizing val MAE.
- [ ] **Step 2:** Run head-to-head 2024-2025 weeks 4-18, report per-position MAE. Gates: ensemble must beat **all** of `MAE<4.163, corr>0.6918, pairwise>77.7%`. Also report per-year 2024 vs 2025 to catch overfit.
- [ ] **Step 3:** Only if gates pass: keep `w` and results. Else REJECTED — stop before integration.

---

### Task 7: Integration behind `use_ml` flag

**Files:** `src/ffanalytics/stat_projector.py`, `src/ffanalytics/projection.py` (if needed), `tests/test_stat_projector_ml.py`

- [ ] **Step 1:** Add `def project_player_stats(..., use_ml=False)` guard:
  ```python
  if use_ml:
      try:
          import xgboost
          # load booster once (module-level cache, no per-request disk I/O)
      except ImportError:
          use_ml = False  # fallback
  ```
- [ ] **Step 2:** When `use_ml=True`, build feature row for the target week (using same `pbp_cache` + `implied_total`/weather), predict `xgb_pts`, ensemble with stat `w` from meta, return as single-point projection (or distribute to stat dict if stat-level).
- [ ] **Step 3:** Thread `use_ml` through `build_weekly_projections(use_ml=False)` (default preserves zero-dep behavior).
- [ ] **Step 4:** Tests: `test_ml_fallback_without_xgboost` (monkeypatch import fail → returns stat result), `test_ml_ensemble_beats_baseline` (mock booster returns val).
- [ ] **Step 5:** `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` still 51+ new tests pass. Manual: `SLEEPER_LEAGUE_ID=1397736035240173568 python -c "sys.path.insert(0,'src'); from ffanalytics.stat_projector import project_player_stats; print(project_player_stats([...],'WR', use_ml=False))"` unchanged.
- [ ] **Step 6:** Commit: `feat: ML ensemble behind use_ml flag (falls back to stat model)`

---

### Deferred / Not in this plan

- PBP stat-level prediction (predict each `passing_yards` etc.) — phase 2 if point-level fails.
- Per-position separate XGB boosters — only if single model underfits QB.
- DB table for PBP cache — file cache is sufficient for one league.
- Hub UI for `use_ml` toggle — decision layer stays agnostic; API can expose `?use_ml=true` later.
