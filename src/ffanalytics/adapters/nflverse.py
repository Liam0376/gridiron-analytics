"""Wraps nflreadpy. This is the ONLY file in the project allowed to import
nflreadpy / touch a Polars object — every function here returns plain
list[dict] so Polars never leaks into the rest of the codebase (see
Global Constraints in the plan)."""

import logging
import random
import time

logger = logging.getLogger(__name__)

def _nfl_module(nfl_module):
    if nfl_module is not None:
        return nfl_module
    import nflreadpy
    return nflreadpy

def _call_with_retry(fn, max_retries=3, backoff_base=1.5):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            # why log+jitter: prior bare-Except retry was silent (failures
            # invisible until refresh_log) and thundering-herd prone; keep
            # 3x/backoff semantics, jitter is additive only.
            logger.warning(
                "nflverse: attempt %d/%d failed (%s); retrying",
                attempt + 1, max_retries, exc,
            )
            time.sleep(backoff_base * (attempt + 1) + random.uniform(0, 0.5))

def get_weekly_player_stats(season: int, nfl_module=None) -> list[dict]:
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_player_stats(seasons=[season]))
    return frame.to_dicts()

def get_injury_history(season: int, nfl_module=None) -> list[dict]:
    nfl = _nfl_module(nfl_module)
    frame = _call_with_retry(lambda: nfl.load_injuries(seasons=[season]))
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
    frame = _call_with_retry(lambda: nfl.load_players())
    return frame.to_dicts()