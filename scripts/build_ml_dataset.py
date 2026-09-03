#!/usr/bin/env python3
"""Utility to build ML dataset JSONL from cached nflverse stats/schedule + PBP.

Dumps data/ml/train_2023_2024.jsonl + val_2025.jsonl (and full) using only
cached files — no network. If PBP cache missing, builds features with
opportunity defaults 0 but still produces dataset.

Usage:
  SLEEPER_LEAGUE_ID=test .venv/bin/python scripts/build_ml_dataset.py
  SLEEPER_LEAGUE_ID=test /opt/homebrew/bin/python3 scripts/build_ml_dataset.py
"""

import json
import os
import sys
from pathlib import Path

# Ensure SLEEPER_LEAGUE_ID doesn't break import (features doesn't need it)
os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

PERSISTENT_CACHE = REPO_ROOT / "data" / "nfl_cache"
ALT_CACHE = REPO_ROOT / "nfl_cache"
OUT_DIR = REPO_ROOT / "data" / "ml"

CACHE_CANDIDATES = [PERSISTENT_CACHE, ALT_CACHE]


def _load_json_from_caches(filename: str):
    for base in CACHE_CANDIDATES:
        p = base / filename
        if p.exists():
            try:
                with open(p) as f:
                    data = json.load(f)
                print(f"Loaded {filename} from {base} ({len(data)} records)")
                return data
            except Exception as e:
                print(f"Failed to load {p}: {e}")
                continue
    print(f"WARNING: {filename} not found in any cache {CACHE_CANDIDATES}")
    return None


def _load_all_stats(seasons=(2023, 2024, 2025)):
    all_stats = []
    for season in seasons:
        data = _load_json_from_caches(f"stats_{season}.json")
        if data is not None:
            all_stats.extend(data)
        else:
            print(f"Missing stats_{season}.json — skipping")
    return all_stats


def _load_all_schedules(seasons=(2023, 2024, 2025)):
    all_sched = []
    for season in seasons:
        data = _load_json_from_caches(f"schedule_{season}.json")
        if data is not None:
            all_sched.extend(data)
        else:
            print(f"Missing schedule_{season}.json — skipping")
    return all_sched


def _load_all_pbp(seasons=(2023, 2024, 2025)):
    all_pbp = []
    found_any = False
    for season in seasons:
        data = _load_json_from_caches(f"pbp_{season}.json")
        if data is not None:
            # Ensure season field present
            for r in data:
                if "season" not in r:
                    r["season"] = season
            all_pbp.extend(data)
            found_any = True
        else:
            # No pbp cache is okay — per spec build without it
            pass
    if not found_any:
        print("No PBP cache found — building features with opportunity defaults 0 (per spec)")
    else:
        print(f"Loaded PBP total {len(all_pbp)} rows across {seasons}")
    return all_pbp if found_any else None


def main():
    print("=== Building ML dataset ===")
    print(f"Repo root: {REPO_ROOT}")
    print(f"Caches: {CACHE_CANDIDATES}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    seasons = (2023, 2024, 2025)
    all_stats = _load_all_stats(seasons)
    all_schedules = _load_all_schedules(seasons)
    pbp_features = _load_all_pbp(seasons)

    print(f"\nTotal stats loaded: {len(all_stats)}")
    print(f"Total schedules loaded: {len(all_schedules)}")
    if pbp_features is None:
        print("PBP features: None (fallback to 0)")
    else:
        print(f"PBP features: {len(pbp_features)} rows")

    if not all_stats or not all_schedules:
        print("ERROR: Need stats and schedules to build dataset")
        sys.exit(1)

    # Build training rows (weeks 4-18)
    from ffanalytics.ml.features import build_training_rows

    rows = build_training_rows(all_stats, all_schedules, pbp_features)
    print(f"\nBuilt {len(rows)} training rows (weeks 4-18, positions QB/RB/WR/TE/K)")

    # Sample count for 2024 week 5
    sample_2024_w5 = [r for r in rows if r.get("season") == 2024 and r.get("week") == 5]
    print(f"Sample row count for 2024 week 5: {len(sample_2024_w5)}")

    # Split time-series: train 2023-2024, val 2025
    train_rows = [r for r in rows if r.get("season") in (2023, 2024)]
    val_rows = [r for r in rows if r.get("season") == 2025]
    full_rows = rows

    # Leakage check
    if train_rows and val_rows:
        max_train = max(r["season"] * 100 + r["week"] for r in train_rows)
        min_val = min(r["season"] * 100 + r["week"] for r in val_rows)
        leak_ok = max_train < min_val
        print(f"Leakage check: max train {max_train} < min val {min_val} ? {leak_ok}")
        if not leak_ok:
            print("ERROR: Leakage detected!")
            sys.exit(1)
        else:
            print("Leakage check PASSED (time-series clean)")
    else:
        print("Leakage check SKIPPED (missing train or val)")
        if not train_rows:
            print(f"train_rows empty: seasons present {[r['season'] for r in rows[:5]]}")
        if not val_rows:
            print(f"val_rows empty: seasons present {sorted(set(r['season'] for r in rows))}")

    # Also check per-row history < target (already enforced, but spot-check)
    for r in rows[:3]:
        assert r["games_played"] < r["week"], f"history leakage for {r}"

    # Dump JSONL
    def dump_jsonl(path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for r in data:
                # Remove non-serializable 'actual_stats' dict if present? Keep but ensure json serializable
                # actual_stats is dict with maybe None values, but json can handle
                # To keep dataset small, we may drop actual_stats blob if too large, but keep for debugging
                # We'll keep a copy without huge nested? We'll just dump row as is, converting non-serializable
                # Ensure all values json serializable: convert any non-serializable
                try:
                    json.dump(r, f)
                except TypeError:
                    # fallback: convert to string
                    clean = {}
                    for k, v in r.items():
                        try:
                            json.dumps(v)
                            clean[k] = v
                        except TypeError:
                            clean[k] = str(v)
                    json.dump(clean, f)
                f.write("\n")
        print(f"Wrote {len(data)} rows to {path}")

    train_path = OUT_DIR / "train_2023_2024.jsonl"
    val_path = OUT_DIR / "val_2025.jsonl"
    full_path = OUT_DIR / "full_2023_2025.jsonl"

    dump_jsonl(train_path, train_rows)
    dump_jsonl(val_path, val_rows)
    dump_jsonl(full_path, full_rows)

    print("\n=== Done ===")
    print(f"Train: {len(train_rows)} -> {train_path}")
    print(f"Val: {len(val_rows)} -> {val_path}")
    print(f"Full: {len(full_rows)} -> {full_path}")
    # Also print row counts for head inspection
    if sample_2024_w5:
        print(f"\nExample row (2024 week 5 first): keys={sorted(sample_2024_w5[0].keys())[:10]}...")
        # Print core features for first row
        ex = sample_2024_w5[0]
        print(f"  player {ex.get('player_id')} {ex.get('player_display_name')} pos {ex.get('position')} team {ex.get('team')} target {ex.get('target'):.2f} games {ex.get('games_played')} implied {ex.get('implied_total'):.1f} spread {ex.get('spread'):.1f}")
        print(f"  target_share_wavg {ex.get('target_share_wavg'):.3f} rush_share {ex.get('rush_share_wavg'):.3f} air_yards {ex.get('air_yards_wavg'):.1f}")

if __name__ == "__main__":
    main()
