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