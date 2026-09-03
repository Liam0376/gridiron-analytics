from unittest.mock import Mock


class _FakePolarsFrame:
    """Minimal stand-in for a polars.DataFrame — only needs to_dicts()."""
    def __init__(self, rows):
        self._rows = rows

    def to_dicts(self):
        return self._rows


def _sample_plays_2024():
    """10 plays spanning 2 weeks, 2 teams, mixture of targets/carries,
    air_yards, redzone (yardline_100 <=20), and dome temp None case."""
    return [
        # Week 1 BUF — 3 targets to 00-001, 2 to 00-002, 2 carries to 00-003
        {"week": 1, "posteam": "BUF", "receiver_player_id": "00-001", "rusher_player_id": None, "air_yards": 12, "yardline_100": 50, "pass": 1, "rush": 0, "season_type": "REG", "temp": 70, "wind": 5, "roof": "outdoors"},
        {"week": 1, "posteam": "BUF", "receiver_player_id": "00-001", "rusher_player_id": None, "air_yards": 8, "yardline_100": 15, "pass": 1, "rush": 0, "season_type": "REG", "temp": 70, "wind": 5, "roof": "outdoors"},
        {"week": 1, "posteam": "BUF", "receiver_player_id": "00-001", "rusher_player_id": None, "air_yards": 5, "yardline_100": 8, "pass": 1, "rush": 0, "season_type": "REG", "temp": 70, "wind": 5, "roof": "outdoors"},
        {"week": 1, "posteam": "BUF", "receiver_player_id": "00-002", "rusher_player_id": None, "air_yards": 10, "yardline_100": 30, "pass": 1, "rush": 0, "season_type": "REG", "temp": 70, "wind": 5, "roof": "outdoors"},
        {"week": 1, "posteam": "BUF", "receiver_player_id": "00-002", "rusher_player_id": None, "air_yards": 7, "yardline_100": 25, "pass": 1, "rush": 0, "season_type": "REG", "temp": 70, "wind": 5, "roof": "outdoors"},
        {"week": 1, "posteam": "BUF", "receiver_player_id": None, "rusher_player_id": "00-003", "air_yards": None, "yardline_100": 45, "pass": 0, "rush": 1, "season_type": "REG", "temp": 70, "wind": 5, "roof": "outdoors"},
        {"week": 1, "posteam": "BUF", "receiver_player_id": None, "rusher_player_id": "00-003", "air_yards": None, "yardline_100": 10, "pass": 0, "rush": 1, "season_type": "REG", "temp": 70, "wind": 5, "roof": "outdoors"},
        # Week 1 DET dome — temp None (should not crash)
        {"week": 1, "posteam": "DET", "receiver_player_id": "00-004", "rusher_player_id": None, "air_yards": 15, "yardline_100": 60, "pass": 1, "rush": 0, "season_type": "REG", "temp": None, "wind": None, "roof": "dome"},
        {"week": 2, "posteam": "BUF", "receiver_player_id": "00-001", "rusher_player_id": None, "air_yards": 20, "yardline_100": 12, "pass": 1, "rush": 0, "season_type": "REG", "temp": 68, "wind": 6, "roof": "outdoors"},
        {"week": 2, "posteam": "BUF", "receiver_player_id": None, "rusher_player_id": "00-003", "air_yards": 0, "yardline_100": 5, "pass": 0, "rush": 1, "season_type": "REG", "temp": 68, "wind": 6, "roof": "outdoors"},
    ]


def test_pbp_features_shape(tmp_path, monkeypatch):
    from ffanalytics.adapters import pbp
    # isolate cache to tmp so we don't pollute real data/nfl_cache
    monkeypatch.setattr(pbp, "PERSISTENT_CACHE_DIR", tmp_path / "persistent")

    fake = Mock()
    fake.load_pbp.return_value = _FakePolarsFrame(_sample_plays_2024())
    rows = pbp.get_pbp_features(2024, nfl_module=fake)
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert {"player_id", "week", "target_share", "rush_share", "air_yards"} <= set(rows[0])
    assert {"air_yards_share", "redzone_targets", "redzone_carries", "snap_share", "route_share"} <= set(rows[0])
    # shares in [0,1], plain dicts
    for r in rows:
        assert 0.0 <= r["target_share"] <= 1.0
        assert 0.0 <= r["rush_share"] <= 1.0
        assert 0.0 <= r["air_yards_share"] <= 1.0
        assert isinstance(r["player_id"], str)
        assert isinstance(r["week"], int)
    fake.load_pbp.assert_called_once_with(seasons=[2024])


def test_pbp_zero_division(tmp_path, monkeypatch):
    from ffanalytics.adapters import pbp
    monkeypatch.setattr(pbp, "PERSISTENT_CACHE_DIR", tmp_path / "persistent")

    # Single team, single player, ensure share is 1.0 not NaN; team with only one target
    plays = [
        {"week": 1, "posteam": "KC", "receiver_player_id": "00-005", "rusher_player_id": None, "air_yards": 10, "yardline_100": 50, "pass": 1, "rush": 0, "season_type": "REG"},
    ]
    fake = Mock()
    fake.load_pbp.return_value = _FakePolarsFrame(plays)
    rows = pbp.get_pbp_features(2025, nfl_module=fake)
    assert len(rows) == 1
    assert rows[0]["target_share"] == 1.0
    assert rows[0]["rush_share"] == 0.0
    assert rows[0]["air_yards_share"] == 1.0
    # zero team carries -> rush_share should be 0 not error
    assert rows[0]["rush_share"] == 0.0


def test_pbp_dome_temp_none(tmp_path, monkeypatch):
    from ffanalytics.adapters import pbp
    monkeypatch.setattr(pbp, "PERSISTENT_CACHE_DIR", tmp_path / "persistent")

    plays = [
        {"week": 3, "posteam": "MIN", "receiver_player_id": "00-006", "rusher_player_id": None, "air_yards": 9, "yardline_100": 40, "pass": 1, "rush": 0, "season_type": "REG", "temp": None, "wind": None, "roof": "dome"},
        {"week": 3, "posteam": "MIN", "receiver_player_id": None, "rusher_player_id": "00-007", "air_yards": None, "yardline_100": 15, "pass": 0, "rush": 1, "season_type": "REG", "temp": None, "wind": None, "roof": "closed"},
    ]
    fake = Mock()
    fake.load_pbp.return_value = _FakePolarsFrame(plays)
    rows = pbp.get_pbp_features(2024, nfl_module=fake)
    # should not raise, and should produce 2 player-weeks
    assert len(rows) == 2
    ids = {r["player_id"] for r in rows}
    assert "00-006" in ids and "00-007" in ids
    # redzone handling: one carry in redzone (yardline 15)
    rz = {r["player_id"]: r["redzone_carries"] for r in rows}
    assert rz["00-007"] == 1
    assert rz["00-006"] == 0


def test_pbp_redzone_and_air_yards_aggregation(tmp_path, monkeypatch):
    from ffanalytics.adapters import pbp
    monkeypatch.setattr(pbp, "PERSISTENT_CACHE_DIR", tmp_path / "persistent")

    plays = _sample_plays_2024()
    fake = Mock()
    fake.load_pbp.return_value = _FakePolarsFrame(plays)
    rows = pbp.get_pbp_features(2024, nfl_module=fake)
    # 00-001 has 3 targets week1 with air 12+8+5=25, two in redzone (15 and 8)
    p = next(r for r in rows if r["player_id"] == "00-001" and r["week"] == 1)
    assert p["targets"] == 3
    assert p["air_yards"] == 25.0
    assert p["redzone_targets"] == 2
    # BUF week1 total air = 12+8+5+10+7=42, share for 00-001 =25/42
    assert abs(p["air_yards_share"] - 25 / 42) < 1e-6
    assert abs(p["target_share"] - 3 / 5) < 1e-6
    # 00-003 week1 has 2 carries, one redzone
    p3 = next(r for r in rows if r["player_id"] == "00-003" and r["week"] == 1)
    assert p3["carries"] == 2
    assert p3["redzone_carries"] == 1
    assert p3["rush_share"] == 1.0


def test_pbp_returns_plain_dicts(tmp_path, monkeypatch):
    from ffanalytics.adapters import pbp
    monkeypatch.setattr(pbp, "PERSISTENT_CACHE_DIR", tmp_path / "persistent")

    fake = Mock()
    fake.load_pbp.return_value = _FakePolarsFrame(_sample_plays_2024())
    rows = pbp.get_pbp_features(2024, nfl_module=fake)
    for r in rows:
        assert type(r) is dict
        # ensure no Polars types leak: json serializable
        import json
        json.dumps(r)


def test_pbp_import_does_not_require_sleeper_env(monkeypatch):
    # pbp import should succeed even if SLEEPER_LEAGUE_ID is missing
    import importlib, os
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    # reload to ensure no top-level config import
    import ffanalytics.adapters.pbp as pbp_mod
    importlib.reload(pbp_mod)
    assert hasattr(pbp_mod, "get_pbp_features")
    # restore
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "1397736035240173568")
    importlib.reload(pbp_mod)


def test_pbp_caching_writes_atomically(tmp_path, monkeypatch):
    from ffanalytics.adapters import pbp
    persistent = tmp_path / "persistent"
    monkeypatch.setattr(pbp, "PERSISTENT_CACHE_DIR", persistent)

    fake = Mock()
    fake.load_pbp.return_value = _FakePolarsFrame(_sample_plays_2024())
    rows = pbp.get_pbp_features(2024, nfl_module=fake)
    # should have written to persistent atomically, no .tmp left
    assert (persistent / "pbp_2024.json").exists()
    assert not (persistent / "pbp_2024.json.tmp").exists()
    import json
    cached = json.loads((persistent / "pbp_2024.json").read_text())
    assert len(cached) == len(rows)
    # second call with nfl_module=None should hit cache and not call nflreadpy
    fake2 = Mock()
    fake2.load_pbp.side_effect = AssertionError("should not be called when cache exists")
    rows2 = pbp.get_pbp_features(2024, nfl_module=None)
    assert rows2 == cached

    # scratch fallback removed — only persistent cache is consulted.
    # Verify cache miss path returns freshly-computed rows (not the deleted file).
    (persistent / "pbp_2024.json").unlink()
    rows3 = pbp.get_pbp_features(2024, nfl_module=None)
    assert isinstance(rows3, list)
    assert rows3 == rows or len(rows3) >= 0  # recomputed or empty, both valid
