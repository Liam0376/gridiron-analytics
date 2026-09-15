from ffanalytics.stat_projector import compute_ros_projections


def _full_schedule(bye_team=None, bye_week=None):
    """Generate a full 18-week schedule. Optionally place one team on bye."""
    teams = ["KC", "BUF", "ATL", "SF"]
    sched = []
    for wk in range(1, 19):
        pairs = [("KC", "BUF"), ("ATL", "SF")]
        for home, away in pairs:
            if bye_team and home == bye_team and wk == bye_week:
                continue
            if bye_team and away == bye_team and wk == bye_week:
                continue
            sched.append({"week": wk, "home_team": home, "away_team": away, "season": 2026})
    return sched


def test_ros_basic():
    projs = [
        {"player_id": "p1", "player_display_name": "Test QB", "position": "QB",
         "team": "KC", "_neutral_points": 20.0},
        {"player_id": "p2", "player_display_name": "Test WR", "position": "WR",
         "team": "BUF", "_neutral_points": 15.0},
    ]
    sched = _full_schedule()
    ros = compute_ros_projections(projs, sched, current_week=1)
    assert len(ros) == 2
    kc = [r for r in ros if r["team"] == "KC"][0]
    buf = [r for r in ros if r["team"] == "BUF"][0]
    assert kc["remaining_games"] == 18
    assert kc["ros_points"] == 360.0
    assert buf["remaining_games"] == 18
    assert buf["ros_points"] == 270.0


def test_ros_bye_week():
    projs = [
        {"player_id": "p1", "player_display_name": "Test RB", "position": "RB",
         "team": "KC", "_neutral_points": 18.0},
    ]
    sched = _full_schedule(bye_team="KC", bye_week=5)
    ros = compute_ros_projections(projs, sched, current_week=1)
    assert len(ros) == 1
    assert ros[0]["remaining_games"] == 17
    assert ros[0]["ros_points"] == 306.0


def test_ros_mid_season():
    projs = [
        {"player_id": "p1", "player_display_name": "Test QB", "position": "QB",
         "team": "KC", "_neutral_points": 20.0},
    ]
    sched = _full_schedule()
    ros = compute_ros_projections(projs, sched, current_week=10)
    assert len(ros) == 1
    assert ros[0]["remaining_games"] == 9
    assert ros[0]["ros_points"] == 180.0


def test_ros_skips_neutral_zero():
    projs = [
        {"player_id": "p1", "player_display_name": "No History", "position": "WR",
         "team": "KC", "_neutral_points": None},
        {"player_id": "p2", "player_display_name": "Valid", "position": "QB",
         "team": "KC", "_neutral_points": 20.0},
    ]
    sched = _full_schedule()
    ros = compute_ros_projections(projs, sched, current_week=1)
    assert len(ros) == 1
    assert ros[0]["player_id"] == "p2"


def test_ros_sorted_by_points():
    projs = [
        {"player_id": "p1", "player_display_name": "Low", "position": "K",
         "team": "KC", "_neutral_points": 8.0},
        {"player_id": "p2", "player_display_name": "High", "position": "QB",
         "team": "KC", "_neutral_points": 25.0},
    ]
    sched = _full_schedule()
    ros = compute_ros_projections(projs, sched, current_week=1)
    assert ros[0]["player_display_name"] == "High"
    assert ros[1]["player_display_name"] == "Low"
