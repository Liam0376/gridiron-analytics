import os
os.environ.setdefault("SLEEPER_LEAGUE_ID", "test")

from ffanalytics.ml.features import build_training_rows, EXPECTED_FEATURE_KEYS


def _make_stat(pid, season, week, position, team, **extra):
    base = {
        "player_id": pid,
        "player_display_name": f"Player {pid}",
        "player_name": f"P.{pid}",
        "season": season,
        "week": week,
        "season_type": "REG",
        "position": position,
        "team": team,
        "recent_team": team,
        "opponent_team": "BUF",
        "passing_yards": 0,
        "passing_tds": 0,
        "passing_interceptions": 0,
        "rushing_yards": 10 if position in ("RB", "QB") else 0,
        "rushing_tds": 0,
        "receiving_yards": 20 if position in ("WR", "TE") else 0,
        "receiving_tds": 0,
        "receptions": 2 if position in ("WR", "TE", "RB") else 0,
        "targets": 3 if position in ("WR", "TE") else 0,
        "fumbles_lost_total": 0,
        "passing_2pt_conversions": 0,
        "rushing_2pt_conversions": 0,
        "receiving_2pt_conversions": 0,
        "passing_40": 0,
        "rushing_40": 0,
        "receiving_40": 0,
        "fg_made_0_19": 0,
        "fg_made_20_29": 0,
        "fg_made_30_39": 0,
        "fg_made_40_49": 0,
        "fg_made_50_59": 0,
        "fg_missed": 0,
        "pat_made": 0,
        "def_fumbles_forced": 0,
    }
    base.update(extra)
    return base


def _make_sched(season, week, home, away, total_line=44.0, spread_line=3.0, temp=68, wind=5, roof="outdoors"):
    return {
        "season": season,
        "week": week,
        "game_type": "REG",
        "home_team": home,
        "away_team": away,
        "total_line": total_line,
        "spread_line": spread_line,
        "temp": temp,
        "wind": wind,
        "roof": roof,
    }


def _make_pbp(pid, season, week, **vals):
    base = {
        "player_id": pid,
        "season": season,
        "week": week,
        "team": vals.get("team", "BUF"),
        "targets": 1,
        "carries": 0,
        "target_share": vals.get("target_share", 0.2),
        "rush_share": vals.get("rush_share", 0.0),
        "air_yards": vals.get("air_yards", 10.0),
        "air_yards_share": vals.get("air_yards_share", 0.2),
        "redzone_targets": vals.get("redzone_targets", 0),
        "redzone_carries": vals.get("redzone_carries", 0),
        "snap_share": vals.get("snap_share", 0.5),
        "route_share": vals.get("route_share", 0.5),
    }
    base.update(vals)
    return base


def test_build_training_rows_no_leakage():
    # Build synthetic data for 2 train seasons + 1 val season, weeks 1-6
    stats = []
    schedules = []
    pbp = []

    for season in (2023, 2024, 2025):
        # schedules for weeks 1-6
        for wk in range(1, 7):
            schedules.append(_make_sched(season, wk, "BUF", "MIA"))
            schedules.append(_make_sched(season, wk, "KC", "DEN"))
        # one player across weeks 1-6
        pid = "00-001"
        for wk in range(1, 7):
            # Vary stats slightly to check trend
            stats.append(_make_stat(pid, season, wk, "WR", "BUF", receiving_yards=20 + wk * 5, receptions=2 + (wk % 2)))
            pbp.append(_make_pbp(pid, season, wk, target_share=0.2, air_yards=10.0, air_yards_share=0.2))
        # also a second player with high target share only in week 5 to test leakage
        pid2 = "00-002"
        for wk in range(1, 7):
            share = 0.2
            ay = 10.0
            if wk == 5:
                share = 1.0  # spike in target week
                ay = 100.0
            stats.append(_make_stat(pid2, season, wk, "WR", "BUF"))
            pbp.append(_make_pbp(pid2, season, wk, target_share=share, air_yards=ay, air_yards_share=share))

    rows = build_training_rows(stats, schedules, pbp)
    # only weeks 4-18 should be present
    for r in rows:
        assert 4 <= r["week"] <= 18, f"week out of range {r['week']}"
        # games_played should be week-1 for our synthetic (since we have weeks 1..6 continuous)
        # but for week 4, games_played should be 3 (weeks 1-3)
        # general: history only < target, so games_played < week
        assert r["games_played"] < r["week"], f"games_played {r['games_played']} should be < week {r['week']}"
        # also check that target week not included in history via wavg: for pid 00-002 week 5, wavg should be based on 0.2 not 1.0
        # so target_share_wavg should be 0.2 for week 5 (since prior weeks all 0.2)
        if r["player_id"] == "00-002" and r["week"] == 5:
            assert abs(r["target_share_wavg"] - 0.2) < 1e-6, f"leakage: target_share_wavg {r['target_share_wavg']} should be 0.2 not include week5 1.0"
            assert abs(r["air_yards_wavg"] - 10.0) < 1e-6

    # Time-series split: train 2023-2024, val 2025 -> max train season/week < min val
    train = [r for r in rows if r["season"] in (2023, 2024)]
    val = [r for r in rows if r["season"] == 2025]
    assert train and val, "need both train and val rows"
    max_train = max(r["season"] * 100 + r["week"] for r in train)
    min_val = min(r["season"] * 100 + r["week"] for r in val)
    assert max_train < min_val, f"leakage: max train {max_train} should be < min val {min_val}"

    # Also check per-player history only < target by verifying week ordering
    # For each player-season, rows should be sorted and games_played increases with week
    from collections import defaultdict
    by_player = defaultdict(list)
    for r in rows:
        by_player[(r["player_id"], r["season"])].append(r)
    for key, lst in by_player.items():
        lst.sort(key=lambda x: x["week"])
        for i in range(1, len(lst)):
            assert lst[i]["games_played"] > lst[i-1]["games_played"] or lst[i]["games_played"] == lst[i-1]["games_played"] + 1 or lst[i]["games_played"] >= lst[i-1]["games_played"]


def test_feature_keys_complete():
    stats = []
    schedules = []
    pbp = []
    # minimal single season
    for wk in range(1, 6):
        schedules.append(_make_sched(2024, wk, "BUF", "MIA"))
    pid = "00-003"
    for wk in range(1, 6):
        stats.append(_make_stat(pid, 2024, wk, "WR", "BUF"))
        pbp.append(_make_pbp(pid, 2024, wk))
    # also include QB/RB/TE/K to ensure one-hot handling
    for pos, team in [("QB", "BUF"), ("RB", "BUF"), ("TE", "BUF"), ("K", "BUF")]:
        pidp = f"00-{pos}"
        for wk in range(1, 6):
            stats.append(_make_stat(pidp, 2024, wk, pos, team))
            pbp.append(_make_pbp(pidp, 2024, wk))

    rows = build_training_rows(stats, schedules, pbp)
    assert rows, "should produce rows"
    # Expected keys from spec
    expected = [
        "target_share_wavg", "rush_share_wavg", "air_yards_wavg", "air_yards_share_wavg",
        "redzone_targets_wavg", "redzone_carries_wavg", "snap_share_wavg",
        "implied_total", "spread", "wind", "temp", "is_dome",
        "games_played", "position_QB", "position_RB", "position_WR", "position_TE", "position_K",
        "recent_trend", "trend_slope", "team",
        "target",
    ]
    # also check projected features
    proj_keys = ["pass_yd_proj", "rush_yd_proj", "rec_yd_proj", "rec_proj", "passing_yards_proj"]
    expected.extend(proj_keys)

    for r in rows:
        for k in expected:
            assert k in r, f"missing feature key {k} in row {r.get('player_id')} week {r.get('week')}"
        # values should be numeric (or string for team)
        assert isinstance(r["target_share_wavg"], (int, float))
        assert 0.0 <= r["target_share_wavg"] <= 1.0
        assert 0.0 <= r["rush_share_wavg"] <= 1.0
        assert isinstance(r["implied_total"], (int, float))
        assert isinstance(r["is_dome"], int)
        assert isinstance(r["games_played"], int)
        # one-hot sum should be 1
        s = r["position_QB"] + r["position_RB"] + r["position_WR"] + r["position_TE"] + r["position_K"]
        assert s == 1, f"one-hot sum should be 1 got {s} for {r['position']}"

    # Check all EXPECTED_FEATURE_KEYS from module are present (at least those)
    for r in rows[:1]:
        for k in EXPECTED_FEATURE_KEYS:
            # some keys like route_share_wavg optional, but our EXPECTED_FEATURE_KEYS should be subset
            if k in expected or k in ["route_share_wavg", "recent_trend_slope", "actual_points", "season", "week", "player_id", "season"]:
                continue
            # ensure not missing critical
            assert k in r or k in ["route_share_wavg"], f"module expected key {k} missing"


def test_pbp_missing_fallback():
    stats = []
    schedules = []
    for wk in range(1, 6):
        schedules.append(_make_sched(2024, wk, "BUF", "MIA", temp=70, wind=8))
    pid = "00-004"
    for wk in range(1, 6):
        stats.append(_make_stat(pid, 2024, wk, "WR", "BUF"))

    # Case 1: pbp_features = None
    rows = build_training_rows(stats, schedules, None)
    assert rows, "should produce rows even with pbp None"
    for r in rows:
        assert r["target_share_wavg"] == 0.0
        assert r["rush_share_wavg"] == 0.0
        assert r["air_yards_wavg"] == 0.0
        assert r["snap_share_wavg"] == 0.0
        # should not crash, other features present
        assert "implied_total" in r

    # Case 2: empty list
    rows2 = build_training_rows(stats, schedules, [])
    assert rows2
    for r in rows2:
        assert r["target_share_wavg"] == 0.0

    # Case 3: pbp missing for some players only (partial)
    pbp_partial = [_make_pbp("00-OTHER", 2024, 1, target_share=0.5)]
    rows3 = build_training_rows(stats, schedules, pbp_partial)
    for r in rows3:
        # pid 00-004 has no pbp, should still be 0
        assert r["target_share_wavg"] == 0.0

    # Case 4: schedule missing (no Vegas/weather) -> defaults 0, no crash
    rows4 = build_training_rows(stats, [], None)
    assert rows4
    for r in rows4:
        assert r["implied_total"] == 0.0
        assert r["spread"] == 0.0

    # Legacy single-row signature with missing pbp should also not crash
    from ffanalytics.ml.features import build_training_rows as btr
    history = [_make_stat(pid, 2024, wk, "WR", "BUF") for wk in range(1, 4)]
    # single row call with pbp_cache None
    single = btr(season=2024, week=4, player_history=history, pbp_cache=None, schedule=schedules, position="WR")
    # legacy returns list with one dict or dict; handle both
    if isinstance(single, list):
        assert single[0]["target_share_wavg"] == 0.0
    else:
        assert single["target_share_wavg"] == 0.0


def test_no_defense_feature_leak():
    # Ensure no opponent defense feature is present
    stats = [_make_stat("00-005", 2024, wk, "WR", "BUF") for wk in range(1, 6)]
    schedules = [_make_sched(2024, wk, "BUF", "MIA") for wk in range(1, 6)]
    pbp = [_make_pbp("00-005", 2024, wk) for wk in range(1, 6)]
    rows = build_training_rows(stats, schedules, pbp)
    for r in rows:
        for k in r.keys():
            assert "defense" not in k.lower(), f"defense feature leaked: {k}"
            assert "opponent" not in k.lower() or k == "opponent_team", f"opponent feature leaked: {k}"
            assert "rest" not in k.lower(), f"rest feature leaked: {k}"
        # ensure home/away not as feature
        assert "is_home" not in r
        # Rest is rejected, also check no EWMA/rest-like keys
        assert "ewma" not in "".join(r.keys()).lower()
