from ffanalytics.game_predictions import devig_two_way, predicted_score, game_prediction


def test_devig_two_way_removes_vig():
    # -110/-110 (standard two-sided vig) -> exactly 0.5/0.5 after devig
    p_a, p_b = devig_two_way(-110, -110)
    assert round(p_a, 4) == 0.5
    assert round(p_b, 4) == 0.5


def test_devig_two_way_favorite_underdog():
    # real row from validation: PHI -425 home, DAL +330 away
    p_home, p_away = devig_two_way(-425, 330)
    assert p_home > p_away
    assert round(p_home + p_away, 6) == 1.0
    assert 0.75 < p_home < 0.8


def test_devig_two_way_zero_prices_no_crash():
    # why: american_to_prob raises on price==0 (not a legal American odds
    # value); devig must not crash on a degenerate/missing-line input.
    p_a, p_b = devig_two_way(100, 100)
    assert round(p_a, 4) == round(p_b, 4)


def test_predicted_score_matches_spread_and_total():
    # BAL@KC 2024wk1 real row: spread_line=3.0 (home/KC favored by 3), total=46.0
    home, away = predicted_score(spread_line=3.0, total_line=46.0)
    assert home == 24.5
    assert away == 21.5
    assert home - away == 3.0
    assert home + away == 46.0


def test_game_prediction_missing_lines_returns_lineless_row():
    # why (user-caught live bug, 2026-09-10): dropping line-less games hid
    # whole teams from the Props tab (books post ~1-2 weeks out; from week
    # 8 nearly every game was dropped). Rows emit with nulls + source
    # "schedule" so every game stays browsable; only missing TEAMS drop.
    pred = game_prediction({"home_team": "KC", "away_team": "BAL"})
    assert pred["home_win_prob"] is None
    assert pred["predicted_home_score"] is None
    assert pred["source"] == "schedule"
    assert pred["final"] is False
    assert game_prediction({"home_team": "KC"}) is None
    assert game_prediction({}) is None


def test_game_prediction_nan_line_quarantines_row_not_500():
    # why (code-review finding): nflreadpy/Polars can hand back NaN for a
    # "present" (not None) line — must degrade to the lineless row, never
    # let NaN reach json.dumps and crash the whole /games/predictions
    # response.
    import math

    row = {
        "game_id": "2024_01_BAL_KC", "season": 2024, "week": 1,
        "home_team": "KC", "away_team": "BAL",
        "home_moneyline": -148, "away_moneyline": 124,
        "spread_line": float("nan"), "total_line": 46.0,
    }
    pred = game_prediction(row)
    assert pred["source"] == "schedule"
    assert pred["home_win_prob"] is None
    assert pred["spread_line"] is None  # NaN never leaks, even partial
    assert pred["total_line"] == 46.0  # finite partial lines are kept
    row["spread_line"] = float("inf")
    assert game_prediction(row)["source"] == "schedule"


def test_game_prediction_full_row():
    row = {
        "game_id": "2024_01_BAL_KC", "season": 2024, "week": 1,
        "home_team": "KC", "away_team": "BAL",
        "home_moneyline": -148, "away_moneyline": 124,
        "spread_line": 3.0, "total_line": 46.0,
        "home_score": 27, "away_score": 20,
    }
    pred = game_prediction(row)
    assert pred["home_team"] == "KC"
    assert pred["away_team"] == "BAL"
    assert pred["home_win_prob"] > pred["away_win_prob"]
    assert round(pred["home_win_prob"] + pred["away_win_prob"], 6) == 1.0
    assert pred["predicted_home_score"] == 24.5
    assert pred["predicted_away_score"] == 21.5
    assert pred["source"] == "market_consensus"
    assert pred["final"] is True
    assert pred["actual_home_score"] == 27
    assert pred["actual_away_score"] == 20


def test_game_prediction_not_final_when_unplayed():
    row = {
        "game_id": "2026_01_SF_LA", "season": 2026, "week": 1,
        "home_team": "LA", "away_team": "SF",
        "home_moneyline": -198, "away_moneyline": 164,
        "spread_line": 3.5, "total_line": 48.5,
        "home_score": None, "away_score": None,
    }
    pred = game_prediction(row)
    assert pred["final"] is False
    assert pred["actual_home_score"] is None
