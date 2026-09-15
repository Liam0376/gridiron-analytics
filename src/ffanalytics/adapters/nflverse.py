"""Wraps nflreadpy. This is the ONLY file in the project allowed to import
nflreadpy / touch a Polars object — every function here returns plain
list[dict] so Polars never leaks into the rest of the codebase (see
Global Constraints in the plan)."""

from ffanalytics.adapters._retry import call_with_retry as _call_with_retry

def _nfl_module(nfl_module):
    if nfl_module is not None:
        return nfl_module
    import nflreadpy
    return nflreadpy

def get_weekly_player_stats(season: int, nfl_module=None) -> list[dict]:
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_player_stats(seasons=[season]), name="nflverse")
    return frame.to_dicts()

def get_injury_history(season: int, nfl_module=None) -> list[dict]:
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_injuries(seasons=[season]), name="nflverse")
    return frame.to_dicts()

def get_player_ids(nfl_module=None) -> list[dict]:
    """Full player-identity master list (~25k rows: gsis_id, display_name,
    position, latest_team, ...) — NOT filtered to this week's box score.
    why this exists (user-caught live bug, 2026-09-10): the sleeper_id<->
    gsis_id name+pos fallback (build_sleeper_xwalk) was built only from
    weekly player_stats rows, so it could only resolve a player who
    happened to have a stat line THIS week. A player who didn't play this
    week (bye, injury, backup) has no such row, even though their gsis_id
    is a stable identity unrelated to whether they played — confirmed
    live: Brock Purdy (real SF starter, just didn't have a week-1 box
    score in this dataset) failed to resolve for exactly this reason, not
    a genuine identity gap like the Kenneth Walker case. load_players()
    covers every player regardless of weekly participation.
    """
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_players(), name="nflverse")
    return frame.to_dicts()


def get_ecr_weekly(nfl_module=None) -> list[dict]:
    """Free weekly expert-consensus ranks (DynastyProcess via nflverse):
    player_name, pos, team, ecr, sd, best, worst, pos_rank, fantasypros_id,
    opponent, bye, start-sit grade. Current week only — scrape_date tells
    which. $0, no key, no scraping (cf. paid adapters/fantasypros.py).
    """
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_ff_rankings(type="week"), name="nflverse")
    return frame.to_dicts()


def get_ff_playerids(nfl_module=None) -> list[dict]:
    """Cross-ID spine (fantasypros_id, gsis_id, sleeper_id, pfr/pff/espn/
    yahoo...). The exact ECR join key source — refreshes rarely, cache it.
    """
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_ff_playerids(), name="nflverse")
    return frame.to_dicts()