"""NFL schedule adapter. Wraps nflreadpy.load_schedules() — no Polars escapes."""


from ffanalytics.adapters._retry import call_with_retry as _call_with_retry

def get_schedule(season: int, week: int | None = None, nfl_module=None) -> list[dict]:
    nfl = nfl_module if nfl_module is not None else __import__("nflreadpy")
    frame = _call_with_retry(lambda: nfl.load_schedules(seasons=[season]), name="schedule")
    rows = frame.to_dicts()
    if week is not None:
        rows = [r for r in rows if r.get("week") == week]
    return rows


def get_team_for_player(rosters: list[dict], player_id: str) -> str | None:
    for roster in rosters:
        if player_id in (roster.get("players") or []):
            return roster.get("owner_id") or str(roster.get("roster_id", ""))
    return None


def get_nfl_team_matchups(schedule: list[dict], week: int) -> dict[str, str]:
    matchups = {}
    for game in schedule:
        if game.get("week") == week:
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            if home and away:
                matchups[home] = away
                matchups[away] = home
    return matchups
