import os
os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

import json
import tempfile
from pathlib import Path

import pytest

from ffanalytics.ml.train_stat_level import FEATURE_COLS, STAT_LIST, STAT_LIST_CORE, PARAMS


def _make_synthetic_row(pid, season, week, position="WR", implied=22.0, spread=3.0):
    """Make minimal training row that satisfies FEATURE_COLS and contains actual_stats."""
    # Determine projected values roughly proportional to target stats
    base_pass_yd = 250 if position == "QB" else 0
    base_rush_yd = 60 if position in ("RB", "QB") else 5
    base_rec_yd = 50 if position in ("WR", "TE") else 5
    # actual stats dict for per-stat y
    actual_stats = {
        "player_id": pid,
        "passing_yards": 200 if position == "QB" else 0,
        "passing_tds": 1 if position == "QB" else 0,
        "passing_interceptions": 0.3 if position == "QB" else 0,
        "rushing_yards": 40 if position == "RB" else (15 if position == "QB" else 5),
        "rushing_tds": 0.2 if position in ("RB", "QB") else 0.02,
        "receiving_yards": 60 if position in ("WR", "TE") else (12 if position == "RB" else 0),
        "receiving_tds": 0.3 if position in ("WR", "TE") else 0.05,
        "receptions": 4 if position in ("WR", "TE", "RB") else 0,
        "fumbles_lost_total": 0.05,
        "fg_made_0_19": 0.1 if position == "K" else 0,
        "fg_made_20_29": 0.3 if position == "K" else 0,
        "fg_made_30_39": 0.2 if position == "K" else 0,
        "fg_made_40_49": 0.2 if position == "K" else 0,
        "fg_made_50_59": 0.05 if position == "K" else 0,
        "fg_missed": 0.05 if position == "K" else 0,
        "pat_made": 1.0 if position == "K" else 0,
    }
    # Add some variance via week/ pid
    # perturb actual to create learning signal
    variance = (hash(pid) % 7) * 0.5 + (week % 3)
    actual_stats["receiving_yards"] += variance * 2
    actual_stats["rushing_yards"] += variance
    if position == "QB":
        actual_stats["passing_yards"] += variance * 10

    # projected features: slightly biased version of actual (stat_projector sim)
    proj = {}
    for stat in ["passing_yards","passing_tds","passing_interceptions","rushing_yards","rushing_tds","receiving_yards","receiving_tds","receptions","fumbles_lost_total","fg_made_0_19","fg_made_20_29","fg_made_30_39","fg_made_40_49","fg_made_50_59","fg_missed","pat_made"]:
        proj[f"{stat}_proj"] = max(0.0, float(actual_stats.get(stat, 0)) * 0.9 + 1.0)  # biased

    # Build row
    row = {
        "player_id": pid,
        "player_display_name": f"Player {pid}",
        "season": season,
        "week": week,
        "team": "BUF",
        "position": position,
        "games_played": min(5, week-1),
        "implied_total": implied,
        "spread": spread,
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
        "actual_stats": actual_stats,
        "target": 0,  # will compute via scoring
        "actual_points": 0,
    }
    # add proj features
    row.update(proj)
    # also add short aliases for completeness (not needed for training but present in real data)
    row["pass_yd_proj"] = row.get("passing_yards_proj", 0)
    row["pass_td_proj"] = row.get("passing_tds_proj", 0)
    row["pass_int_proj"] = row.get("passing_interceptions_proj", 0)
    row["rush_yd_proj"] = row.get("rushing_yards_proj", 0)
    row["rush_td_proj"] = row.get("rushing_tds_proj", 0)
    row["rec_yd_proj"] = row.get("receiving_yards_proj", 0)
    row["rec_td_proj"] = row.get("receiving_tds_proj", 0)
    row["rec_proj"] = row.get("receptions_proj", 0)
    row["fum_lost_proj"] = row.get("fumbles_lost_total_proj", 0)
    # one-hot
    for p in ("QB","RB","WR","TE","K"):
        row[f"position_{p}"] = 1 if position==p else 0
    # compute target points via scoring for points gate
    try:
        from ffanalytics.ml.features import _map_to_scoring_stats
        from ffanalytics.scoring import calculate_fantasy_points, DEFAULT_SCORING
        scoring_stats = _map_to_scoring_stats(actual_stats)
        pts = calculate_fantasy_points(scoring_stats, DEFAULT_SCORING)
    except Exception:
        # fallback manual: approximate
        pts = (actual_stats.get("receptions",0)*1.0 + actual_stats.get("receiving_yards",0)*0.1 + actual_stats.get("rushing_yards",0)*0.1 + actual_stats.get("passing_yards",0)*0.04 +
               actual_stats.get("passing_tds",0)*5 + actual_stats.get("rushing_tds",0)*6 + actual_stats.get("receiving_tds",0)*6 )
    row["target"] = float(pts)
    row["actual_points"] = float(pts)
    # ensure all FEATURE_COLS present
    for c in FEATURE_COLS:
        if c not in row:
            row[c] = 0.0
    return row


def _write_jsonl(path: Path, rows):
    with open(path, "w") as f:
        for r in rows:
            json.dump(r, f)
            f.write("\n")


def test_stat_level_writes_boosters_small(tmp_path):
    """Verify per-stat booster files written on tiny 10-row-per-stat dataset without network, no defense leak."""
    from ffanalytics.ml.train_stat_level import train_stat_level

    train_rows = []
    val_rows = []
    # 20 train rows (2023-2024), 10 val rows (2025) — 10 rows per stat is enough for core stats
    # Create diverse positions to cover all core stats
    positions = ["QB","RB","WR","TE","WR","RB","QB","WR","TE","K"]
    for i in range(20):
        season = 2023 if i < 10 else 2024
        week = 4 + (i % 5)
        pos = positions[i % len(positions)]
        # vary implied to give signal
        implied = 24 if pos in ("QB","WR","TE") else 20
        train_rows.append(_make_synthetic_row(f"00-T{i:02d}", season, week, position=pos, implied=implied))
    for i in range(10):
        season = 2025
        week = 4 + (i % 5)
        pos = positions[i % len(positions)]
        implied = 24 if pos in ("QB","WR","TE") else 20
        val_rows.append(_make_synthetic_row(f"00-V{i:02d}", season, week, position=pos, implied=implied))

    train_path = tmp_path / "train.jsonl"
    val_path = tmp_path / "val.jsonl"
    out_dir = tmp_path / "models" / "stat_level"
    _write_jsonl(train_path, train_rows)
    _write_jsonl(val_path, val_rows)

    status, metrics, meta = train_stat_level(train_path, val_path, out_dir)

    # Checks: at least core stat boosters written (even with 10 rows, train should attempt)
    # For tiny data, some K stats may be skipped due to <5 K rows, but core should be present
    for stat in STAT_LIST_CORE:
        p = out_dir / f"{stat}.json"
        # core stats should be trained (since we have many non-K rows)
        assert p.exists(), f"booster file for {stat} should be written, missing {p}"

    meta_path = out_dir / "meta.json"
    assert meta_path.exists(), "meta.json should be written"
    with open(meta_path) as f:
        meta_json = json.load(f)
    assert "features" in meta_json
    assert "val_mae_per_stat" in meta_json
    assert "val_mae" in meta_json
    assert "status" in meta_json
    assert meta_json["status"] in ("REJECTED", "ACCEPTED", "ACCEPTED_WARNING")
    # feature list must not contain rejected factors
    for col in meta_json["features"]:
        assert "defense" not in col.lower(), f"defense leaked in {col}"
        assert "opponent" not in col.lower(), f"opponent leaked {col}"
        assert "rest" not in col.lower(), f"rest leaked {col}"
        assert "is_home" not in col.lower(), f"home leaked {col}"
        assert "ewma" not in col.lower(), f"ewma leaked {col}"
    # per-stat mae should be numeric for trained stats
    for stat, m in meta_json["val_mae_per_stat"].items():
        if m.get("status") == "TRAINED":
            assert isinstance(m["mae"], (int,float)), f"mae for {stat} should be numeric"
            assert m["mae"] >= 0
    # Ensure train/val seasons correct
    assert meta_json["train_seasons"] == [2023,2024]
    assert meta_json["val_season"] == 2025
    # Ensure no leakage: time-series clean already, but we check rows do not use future week
    # (already guaranteed by dataset, but we assert games_played < week for our synthetic)
    for r in train_rows + val_rows:
        assert r["games_played"] < r["week"]


def test_backtest_stat_level_runs_without_network(tmp_path):
    """Verify backtest runs without network, no defense leak, and writes gated JSON."""
    from ffanalytics.ml.train_stat_level import train_stat_level
    import subprocess
    import sys

    train_rows = []
    val_rows = []
    positions = ["QB","RB","WR","TE","WR","RB","QB","WR","TE","K"]
    for i in range(16):
        season = 2023 if i < 8 else 2024
        week = 4 + (i % 4)
        pos = positions[i % len(positions)]
        train_rows.append(_make_synthetic_row(f"00-T{i:02d}", season, week, position=pos))
    for i in range(8):
        season = 2025
        week = 4 + (i % 4)
        pos = positions[i % len(positions)]
        val_rows.append(_make_synthetic_row(f"00-V{i:02d}", season, week, position=pos))

    train_path = tmp_path / "train.jsonl"
    val_path = tmp_path / "val.jsonl"
    out_dir = tmp_path / "models" / "stat_level"
    _write_jsonl(train_path, train_rows)
    _write_jsonl(val_path, val_rows)

    status, metrics, meta = train_stat_level(train_path, val_path, out_dir)

    # Now run backtest_stat_level.py without network
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "backtest_stat_level.py"
    out_json = tmp_path / "backtest_stat_level_results.json"
    cmd = [
        sys.executable,
        str(script),
        "--train", str(train_path),
        "--val", str(val_path),
        "--model-dir", str(out_dir),
        "--out", str(out_json),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"backtest failed: stdout={result.stdout}\nstderr={result.stderr}"
    assert out_json.exists(), "backtest output should exist"
    with open(out_json) as f:
        data = json.load(f)
    assert "status" in data
    assert data["status"] in ("REJECTED", "ACCEPTED")
    assert "combined_2024_2025" in data
    assert "stat" in data["combined_2024_2025"]
    assert "stat_level" in data["combined_2024_2025"]
    # Check gates present
    assert "baseline" in data
    assert "gates" in data
    # Ensure no defense leak in feature cols
    for col in data.get("feature_cols", []):
        assert "defense" not in col.lower()
        assert "opponent" not in col.lower()
        assert "rest" not in col.lower()
    # Ensure per-position metrics exist
    combined_stat_level = data["combined_2024_2025"]["stat_level"]
    assert "pos_mae" in combined_stat_level
    assert "mae" in combined_stat_level
    assert "corr" in combined_stat_level
    assert "pairwise" in combined_stat_level
    # Ensure reason present
    assert "reason" in data
