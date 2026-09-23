"""Market blend shadow (spec 2026-09-23-market-blend, plan Tasks 1-4)."""
import importlib.util
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ffanalytics import config, db
from ffanalytics.refresh import build_market_snapshot_rows
from ffanalytics.scoring import DEFAULT_SCORING, score_sleeper_stats
from ffanalytics.stat_projector import blend_with_market

_spec = importlib.util.spec_from_file_location(
    "validate_market_blend_2026",
    Path(__file__).resolve().parents[1] / "scripts" / "validate_market_blend_2026.py")
vmb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vmb)


# --- Task 2: blend_with_market ---

def test_blend_skill_positions_use_configured_weight():
    w = config.MARKET_BLEND_W_MODEL
    for pos in ("QB", "RB", "WR", "TE", "wr"):
        assert blend_with_market(10.0, 20.0, pos) == pytest.approx(w * 10 + (1 - w) * 20)


def test_blend_k_passthrough():
    assert blend_with_market(8.0, 12.0, "K") == 8.0


@pytest.mark.parametrize("market", [None, 0.0, -1.0])
def test_blend_missing_or_nonpositive_market_keeps_model(market):
    assert blend_with_market(11.0, market, "RB") == 11.0


def test_blend_out_zero_stays_zero():
    # out-zero must stay absolute: an Out player never picks up 0.75*market
    assert blend_with_market(0.0, 15.0, "WR") == 0.0
    assert blend_with_market(None, 15.0, "WR") is None


def test_blend_weight_one_is_identity_and_zero_is_market():
    assert blend_with_market(9.0, 30.0, "TE", w_model=1.0) == 9.0
    assert blend_with_market(9.0, 30.0, "TE", w_model=0.0) == 30.0


def test_blend_flag_ships_off():
    # Shadow-only until the live gate passes AND Liam confirms (plan Task 5).
    assert config.MARKET_BLEND_ENABLED is False


# --- scoring: Sleeper stat line ---

def test_score_sleeper_stats_dot_product():
    stats = {"pass_yd": 250, "pass_td": 2, "pass_int": 1, "rush_yd": 20, "rec": 0,
             "pts_ppr": 999, "adp_dd_ppr": 12}  # non-scoring keys ignored
    expected = 250 * 0.04 + 2 * 5.0 - 1.0 + 20 * 0.1
    assert score_sleeper_stats(stats, DEFAULT_SCORING) == pytest.approx(expected)


def test_score_sleeper_stats_bad_values_count_zero():
    stats = {"rec": float("nan"), "rec_yd": "x", "rush_yd": float("inf"), "rec_td": 1}
    assert score_sleeper_stats(stats, DEFAULT_SCORING) == pytest.approx(6.0)


def test_score_sleeper_stats_uses_live_settings():
    assert score_sleeper_stats({"rec": 5}, {"rec": 0.5}) == pytest.approx(2.5)


# --- Task 1/3: snapshot rows, pre-kickoff only ---

SCHED = [
    # TNF 20:15 ET on 2026-09-24 (EDT, UTC-4) -> 2026-09-25T00:15Z
    {"season": 2026, "week": 3, "game_type": "REG", "gameday": "2026-09-24",
     "gametime": "20:15", "home_team": "GB", "away_team": "ATL"},
    {"season": 2026, "week": 3, "game_type": "REG", "gameday": "2026-09-27",
     "gametime": "13:00", "home_team": "BUF", "away_team": "MIA"},
    {"season": 2026, "week": 4, "game_type": "REG", "gameday": "2026-10-01",
     "gametime": "20:15", "home_team": "KC", "away_team": "DEN"},
]
PROJS = [
    {"player_id": "gb-wr", "position": "WR", "team": "GB", "projected_points": 10.0},
    {"player_id": "buf-qb", "position": "QB", "team": "BUF", "projected_points": 20.0},
    {"player_id": "buf-k", "position": "K", "team": "BUF", "projected_points": 8.0},
    {"player_id": "mia-rb", "position": "RB", "team": "MIA", "projected_points": 12.0},
    {"player_id": "bye-te", "position": "TE", "team": "KC", "projected_points": 6.0},
]
MARKET = {"gb-wr": {"rec": 5, "rec_yd": 60}, "buf-qb": {"pass_yd": 250, "pass_td": 2}}


def _rows(now):
    return build_market_snapshot_rows(PROJS, MARKET, SCHED, 2026, 3, DEFAULT_SCORING, now)


def test_snapshot_rows_before_all_kickoffs():
    rows = _rows(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
    by_pid = {r[2]: r for r in rows}
    assert set(by_pid) == {"gb-wr", "buf-qb", "mia-rb"}  # K skipped, KC not playing wk 3
    season, week, pid, pos, team, model, market, blend, w, kick, snapped = by_pid["gb-wr"]
    assert (season, week, pos, team, model) == (2026, 3, "WR", "GB", 10.0)
    assert market == pytest.approx(11.0)
    assert blend == pytest.approx(w * 10.0 + (1 - w) * 11.0)
    assert kick == "2026-09-25T00:15:00+00:00"
    # no Sleeper row: market None, blend falls back to model
    assert by_pid["mia-rb"][6] is None and by_pid["mia-rb"][7] == 12.0


def test_snapshot_rows_skip_players_whose_game_started():
    # Friday: TNF over, Sunday games still ahead
    rows = _rows(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
    assert {r[2] for r in rows} == {"buf-qb", "mia-rb"}
    # Monday: everything for week 3 has kicked off -> nothing rewritten
    assert _rows(datetime(2026, 9, 28, 12, tzinfo=timezone.utc)) == []


def test_snapshot_rows_roundtrip_through_migrated_table():
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.get_connection(Path(tmp) / "t.db")
        db.init_schema(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 13
        rows = _rows(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        sql = "INSERT OR REPLACE INTO market_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)"
        conn.executemany(sql, rows)
        conn.executemany(sql, rows)  # idempotent re-refresh
        assert conn.execute("SELECT count(*) FROM market_snapshots").fetchone()[0] == 3
        conn.close()


# --- Task 4: grader ---

def _snap(week, pid, model, blend):
    return {"week": week, "player_id": pid, "model_points": model, "blend_points": blend, "market_points": blend}


def test_grade_waits_below_min_rows():
    snaps = [_snap(4, f"p{i}", 10.0, 12.0) for i in range(5)]
    actual = {(4, f"p{i}"): 12.0 + (i % 2) for i in range(5)}
    res = vmb.grade(snaps, actual, min_rows=10)
    assert res["gate"]["status"] == "WAITING" and res["gate"]["n"] == 5


def test_grade_pass_when_blend_clearly_better():
    snaps, actual = [], {}
    for i in range(60):
        truth = 5.0 + i % 7
        snaps.append(_snap(4 + i % 3, f"p{i}", truth + 4.0 + (i % 5), truth + 0.5 * ((i % 3) - 1) + 0.01 * i))
        actual[(4 + i % 3, f"p{i}")] = truth
    res = vmb.grade(snaps, actual, min_rows=50, t_gate=2.0)
    assert res["gate"]["status"] == "PASS"
    assert res["gate_scope"]["blend"]["mae"] < res["gate_scope"]["model"]["mae"]


def test_grade_ignores_pre_week4_and_unplayed_rows():
    snaps = [_snap(2, "a", 10.0, 11.0), _snap(5, "b", 10.0, 11.0), _snap(5, "dnp", 10.0, 11.0)]
    res = vmb.grade(snaps, {(2, "a"): 11.0, (5, "b"): 11.0}, min_rows=1)
    assert set(res["weeks"]) == {2, 5}
    assert res["gate"]["n"] == 1  # week 2 outside gate scope, DNP never joined


# --- regression: Sleeper market -> gsis join (Sleeper's gsis_id covers ~22%) ---

def test_map_market_to_gsis_fills_gaps_from_playerids():
    from ffanalytics.comparison import map_market_to_gsis
    market = {"1": {"pts_ppr": 10.0}, "2": {"pts_ppr": 8.0}, "3": {"pts_ppr": 5.0}}
    sleeper_players = {"1": {"gsis_id": "00-1"}, "2": {"gsis_id": None}, "3": {}}
    playerids = [{"sleeper_id": "2.0", "gsis_id": "00-2"}, {"sleeper_id": "1", "gsis_id": "00-WRONG"}]
    # without the fallback only player 1 maps (the pre-fix behavior)
    assert set(map_market_to_gsis(market, sleeper_players)) == {"00-1"}
    out = map_market_to_gsis(market, sleeper_players, playerids=playerids)
    assert set(out) == {"00-1", "00-2"}  # Sleeper's own gsis wins for id 1
    assert out["00-2"] == {"pts_ppr": 8.0}
