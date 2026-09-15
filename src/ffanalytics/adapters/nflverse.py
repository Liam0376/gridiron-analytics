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

def get_weekly_rosters(season: int, nfl_module=None) -> list[dict]:
    """Weekly roster snapshots (gsis_id, team, week, status, sleeper_id,
    pfr/pff/espn/yahoo ids, headshot_url) — the current-team source of
    truth. History stat rows carry last season's team; this is what fixes
    movers without name matching (gsis-identity spec).
    """
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_rosters_weekly(seasons=[season]), name="nflverse")
    return frame.to_dicts()


def get_depth_charts(season: int, nfl_module=None) -> list[dict]:
    """Depth-chart snapshot (gsis_id, team, pos_abb, pos_rank, dt).

    nflverse keeps every scrape (dt); refresh-time consumers want the
    CURRENT chart, so this returns latest-dt rows only. Backtests pin an
    older snapshot via the cached file, not via this function.
    """
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_depth_charts(seasons=[season]), name="nflverse")
    rows = frame.to_dicts()
    if not rows:
        return []
    latest = max(str(r.get("dt") or "") for r in rows)
    return [r for r in rows if str(r.get("dt") or "") == latest]


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


def get_opportunity(season: int, nfl_module=None) -> list[dict]:
    """Per-player-per-week opportunity + expected values (gsis player_id,
    team attempts/air-yards totals in-row, receptions_exp /
    rec_yards_gained_exp / rec_touchdown_exp, actuals, diffs).
    Feed includes playoffs (weeks 19-22, no season_type flag) — consumers
    filter week<=18 for REG work. Exact shares need no PBP parsing.
    """
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_ff_opportunity(seasons=[season]), name="nflverse")
    return frame.to_dicts()


def get_ngs_receiving(season: int, nfl_module=None) -> list[dict]:
    """Next Gen Stats receiving (air-yard share, aDOT, cushion/separation).
    Min-targets threshold applies (partial coverage by design) — reserved
    for display/role flags, not projection arms (opportunity air share
    covers the same signal completely). Name-keyed rows (no gsis).
    """
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(
        lambda: nfl.load_nextgen_stats(seasons=[season], stat_type="receiving"),
        name="nflverse")
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