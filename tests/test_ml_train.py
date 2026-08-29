import os
os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

import json
import tempfile
from pathlib import Path

import pytest

from ffanalytics.ml.train import FEATURE_COLS, PARAMS, BASELINE_MAE


def _make_synthetic_row(pid, season, week, position="WR", target_pts=12.0, implied=22.0):
    """Make a minimal training row that satisfies FEATURE_COLS."""
    row = {
        "player_id": pid,
        "player_display_name": f"Player {pid}",
        "season": season,
        "week": week,
        "team": "BUF",
        "position": position,
        "games_played": min(5, week-1),
        "implied_total": implied,
        "spread": 3.0,
        "wind": 5.0,
        "temp": 70.0,
        "is_dome": 0,
        "target_share_wavg": 0.2 if position in ("WR","TE") else 0.0,
        "rush_share_wavg": 0.2 if position=="RB" else 0.0,
        "air_yards_wavg": 30.0 if position=="WR" else 0.0,
        "air_yards_share_wavg": 0.2,
        "redzone_targets_wavg": 0.5,
        "redzone_carries_wavg": 0.3,
        "snap_share_wavg": 0.7,
        "route_share_wavg": 0.6,
        "recent_trend": 0.1,
        "trend_slope": 0.5,
        "recent_trend_slope": 0.5,
        "passing_yards_proj": 250 if position=="QB" else 0,
        "passing_tds_proj": 1.5 if position=="QB" else 0,
        "passing_interceptions_proj": 0.5 if position=="QB" else 0,
        "rushing_yards_proj": 60 if position in ("RB","QB") else 5,
        "rushing_tds_proj": 0.3 if position=="RB" else 0.05,
        "receiving_yards_proj": 50 if position in ("WR","TE") else 5,
        "receiving_tds_proj": 0.3 if position in ("WR","TE") else 0.02,
        "receptions_proj": 4 if position in ("WR","TE","RB") else 0,
        "fumbles_lost_total_proj": 0.1,
        "fg_made_0_19_proj": 0.1 if position=="K" else 0,
        "fg_made_20_29_proj": 0.3 if position=="K" else 0,
        "fg_made_30_39_proj": 0.2 if position=="K" else 0,
        "fg_made_40_49_proj": 0.2 if position=="K" else 0,
        "fg_made_50_59_proj": 0.05 if position=="K" else 0,
        "fg_missed_proj": 0.05 if position=="K" else 0,
        "pat_made_proj": 1.0 if position=="K" else 0,
        "position_QB": 1 if position=="QB" else 0,
        "position_RB": 1 if position=="RB" else 0,
        "position_WR": 1 if position=="WR" else 0,
        "position_TE": 1 if position=="TE" else 0,
        "position_K": 1 if position=="K" else 0,
        "target": float(target_pts),
        "actual_points": float(target_pts),
    }
    # ensure all feature cols present
    for c in FEATURE_COLS:
        if c not in row:
            row[c] = 0.0
    return row


def _write_jsonl(path: Path, rows):
    with open(path, "w") as f:
        for r in rows:
            json.dump(r, f)
            f.write("\n")


def test_train_writes_meta_small(tmp_path):
    """Verify train writes meta and booster on synthetic 10-row dataset without network."""
    from ffanalytics.ml.train import train_model

    train_rows = []
    val_rows = []
    # 10 rows total: 6 train (2023-2024), 4 val (2025) — small but enough for XGB
    for i in range(6):
        season = 2023 if i < 3 else 2024
        week = 4 + (i % 4)
        pos = ["WR","RB","QB","TE"][i % 4]
        # deterministic target
        target = 10 + i*0.5 + (0.2 if pos=="QB" else 0)
        train_rows.append(_make_synthetic_row(f"00-00{i}", season, week, position=pos, target_pts=target))
    for i in range(4):
        season = 2025
        week = 4 + i
        pos = ["WR","RB","TE","K"][i % 4]
        target = 11 + i*0.3
        val_rows.append(_make_synthetic_row(f"00-10{i}", season, week, position=pos, target_pts=target, implied=24.0))

    train_path = tmp_path / "train.jsonl"
    val_path = tmp_path / "val.jsonl"
    out_path = tmp_path / "models" / "xgb_fantasy_v1.json"
    _write_jsonl(train_path, train_rows)
    _write_jsonl(val_path, val_rows)

    status, metrics, meta = train_model(train_path, val_path, out_path)

    # Checks
    assert out_path.exists(), "booster file should be written"
    meta_path = out_path.parent / "xgb_meta.json"
    assert meta_path.exists(), "meta file should be written"
    with open(meta_path) as f:
        meta_json = json.load(f)
    assert "features" in meta_json
    assert "val_mae" in meta_json
    assert "status" in meta_json
    # status should be either REJECTED or ACCEPTED variants
    assert meta_json["status"] in ("REJECTED", "ACCEPTED", "ACCEPTED_WARNING")
    # feature list matches canonical
    assert set(meta_json["features"]) == set(FEATURE_COLS)
    # val_mae is numeric
    assert isinstance(meta_json["val_mae"], (int,float))
    # No defense leakage
    for k in meta_json["features"]:
        assert "defense" not in k.lower()
        assert "rest" not in k.lower()
    # ensure training used only past weeks (time-series clean already checked in train, but we verify rows)
    assert meta_json["train_seasons"] == [2023,2024]
    assert meta_json["val_season"] == 2025


def test_backtest_grid_picks_w_small(tmp_path):
    """Verify backtest grid picks w in [0,1] on synthetic data without real cache."""
    from ffanalytics.ml.train import train_model
    import subprocess
    import sys

    # Build slightly larger synthetic to allow meaningful w grid
    train_rows = []
    val_rows = []
    # Make stat projection intentionally slightly biased so XGB can improve ensemble
    # We'll create train/val where target = stat_pts + noise, and xgb learns correction
    for i in range(10):
        season = 2023 if i < 5 else 2024
        week = 4 + (i % 5)
        # stat projection: base 10, but target is base + 1 for WR, -1 for RB etc to create signal
        pos = ["WR","RB"][i % 2]
        stat_base = 10 if pos=="WR" else 8
        # XGB feature: implied_total correlates with target offset
        implied = 26 if pos=="WR" else 18
        target = stat_base + (2 if pos=="WR" else -1) + (i % 3)*0.1
        row = _make_synthetic_row(f"00-20{i}", season, week, position=pos, target_pts=target, implied=implied)
        # Adjust projected stats to be biased: WR proj undershoots, RB overshoots etc
        if pos=="WR":
            row["receiving_yards_proj"] = 40  # undershoot true 50
            row["receptions_proj"] = 3
        else:
            row["rushing_yards_proj"] = 70  # overshoot
        train_rows.append(row)
    for i in range(6):
        season = 2025
        week = 4 + i
        pos = ["WR","RB","WR","RB","TE","WR"][i % 6]
        stat_base = 10 if pos in ("WR","TE") else 8
        implied = 26 if pos in ("WR","TE") else 18
        target = stat_base + (1.5 if pos in ("WR","TE") else -0.5) + i*0.05
        row = _make_synthetic_row(f"00-30{i}", season, week, position=pos, target_pts=target, implied=implied)
        if pos in ("WR","TE"):
            row["receiving_yards_proj"] = 40
            row["receptions_proj"] = 3
        else:
            row["rushing_yards_proj"] = 70
        val_rows.append(row)

    train_path = tmp_path / "train.jsonl"
    val_path = tmp_path / "val.jsonl"
    out_path = tmp_path / "models" / "xgb_fantasy_v1.json"
    _write_jsonl(train_path, train_rows)
    _write_jsonl(val_path, val_rows)

    # Train
    from ffanalytics.ml.train import train_model
    status, metrics, meta = train_model(train_path, val_path, out_path)

    # Now run backtest logic via direct python call to scripts/backtest_ml.py
    # Use the repo's script but with custom paths
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "backtest_ml.py"
    out_json = tmp_path / "backtest_results.json"
    # Need to pass args; script expects --train --val --model --meta --out
    cmd = [
        sys.executable,
        str(script),
        "--train", str(train_path),
        "--val", str(val_path),
        "--model", str(out_path),
        "--meta", str(out_path.parent / "xgb_meta.json"),
        "--out", str(out_json),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # script should succeed regardless of REJECTED status
    assert result.returncode == 0, f"backtest failed: {result.stdout}\n{result.stderr}"
    assert out_json.exists(), "backtest output should exist"
    with open(out_json) as f:
        data = json.load(f)
    assert "w" in data
    w = data["w"]
    assert isinstance(w, (int,float)), "w should be numeric"
    assert 0.0 <= w <= 1.0, f"w {w} should be in [0,1]"
    # grid should have 21 entries 0.0..1.0 step 0.05
    assert "grid" in data and len(data["grid"]) == 21
    # ensure each grid entry has w and mae
    for entry in data["grid"]:
        assert "w" in entry and "mae" in entry
        assert 0 <= entry["w"] <= 1
    # Ensure no defense leakage in feature cols
    for col in data.get("feature_cols", []):
        assert "defense" not in col.lower()
    # Ensure results contain stat/xgb/ensemble metrics
    assert "combined_2024_2025" in data
    assert "stat" in data["combined_2024_2025"]
    assert "ensemble" in data["combined_2024_2025"]


def test_no_defense_in_train_features():
    """Ensure canonical feature list does not reintroduce rejected defense factors."""
    for col in FEATURE_COLS:
        assert "defense" not in col.lower(), f"defense leaked in feature {col}"
        assert "opponent" not in col.lower() or col == "opponent_team", f"opponent leaked {col}"
        assert "rest" not in col.lower(), f"rest leaked {col}"
        assert "is_home" not in col
        assert "ewma" not in col.lower()
