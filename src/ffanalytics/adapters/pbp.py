"""PBP adapter. Wraps nflreadpy.load_pbp.

This and nflverse.py are the ONLY files allowed to touch Polars objects —
every function here returns plain list[dict] so Polars never leaks into the
rest of the codebase.

Aggregates raw play-by-play rows into per-player-per-week opportunity
features: target_share, rush_share, air_yards, air_yards_share,
redzone_targets, redzone_carries, snap_share/route_share (proxy if direct
snap data unavailable). Handles zero-division and dome temp None.
"""

import json
import logging
import random
import time
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

# Persistent cache dir is the only cache; all callers must populate
# data/nfl_cache/pbp_{season}.json before relying on cached PBP.
_REPO_ROOT = Path(__file__).resolve().parents[3]
PERSISTENT_CACHE_DIR = _REPO_ROOT / "data" / "nfl_cache"


# Audit 6.0: single clear network call site in this module is
# nfl.load_pbp(seasons=[...]) in get_pbp_features, so it gets the same 3x
# retry wrapper as nflverse/schedule/news (log attempts + jitter, additive).
def _call_with_retry(fn, max_retries=3, backoff_base=1.5):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            logger.warning(
                "pbp: attempt %d/%d failed (%s); retrying",
                attempt + 1, max_retries, exc,
            )
            time.sleep(backoff_base * (attempt + 1) + random.uniform(0, 0.5))


def _load_from_cache(season: int) -> list[dict] | None:
    p = PERSISTENT_CACHE_DIR / f"pbp_{season}.json"
    if not p.exists():
        return None
    try:
        with open(p) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        return None
    return None


def _write_cache_atomic(season: int, rows: list[dict]) -> None:
    try:
        PERSISTENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PERSISTENT_CACHE_DIR / f"pbp_{season}.json.tmp"
        final = PERSISTENT_CACHE_DIR / f"pbp_{season}.json"
        with open(tmp, "w") as f:
            json.dump(rows, f)
        tmp.replace(final)
    except Exception:
        # cache write is best-effort; don't fail the request
        pass


def _aggregate_pbp_rows(rows: list[dict], season: int) -> list[dict]:
    # Counters per team-week
    team_targets: dict[tuple[str, int], int] = defaultdict(int)
    team_carries: dict[tuple[str, int], int] = defaultdict(int)
    team_air_yards: dict[tuple[str, int], float] = defaultdict(float)
    team_plays: dict[tuple[str, int], int] = defaultdict(int)

    # Counters per player-week
    player_targets: dict[tuple[str, int], int] = defaultdict(int)
    player_carries: dict[tuple[str, int], int] = defaultdict(int)
    player_air_yards: dict[tuple[str, int], float] = defaultdict(float)
    player_redzone_targets: dict[tuple[str, int], int] = defaultdict(int)
    player_redzone_carries: dict[tuple[str, int], int] = defaultdict(int)
    player_plays: dict[tuple[str, int], int] = defaultdict(int)
    player_team: dict[tuple[str, int], str] = {}

    for r in rows:
        # week — must be int, skip if missing
        wk = r.get("week")
        if wk is None:
            continue
        try:
            wk = int(wk)
        except Exception:
            continue

        posteam = r.get("posteam") or r.get("pos_team") or ""
        if not posteam:
            continue
        posteam = str(posteam)

        # Filter to REG if season_type present (PBP includes POST etc.)
        stype = r.get("season_type")
        if stype is not None and stype != "REG":
            continue

        # Skip deleted/aborted special plays if flagged
        # aborted_play is 1 for aborted snaps (e.g., bad snap)
        if r.get("aborted_play") == 1:
            continue

        # Determine if this is an offensive snap (pass or rush)
        is_pass = False
        is_rush = False
        # Prefer binary flags if present
        if r.get("pass_attempt") == 1 or r.get("pass") == 1:
            is_pass = True
        elif r.get("rush_attempt") == 1 or r.get("rush") == 1:
            is_rush = True
        else:
            pt = r.get("play_type")
            if pt == "pass":
                is_pass = True
            elif pt == "run":
                is_rush = True

        if is_pass or is_rush:
            team_plays[(posteam, wk)] += 1

        # Gather involved players for snap_share proxy
        involved: set[str] = set()

        # Targets — receiver on a pass
        rec_id = (
            r.get("receiver_player_id")
            or r.get("receiver_id")
            or r.get("fantasy_player_id")
            or r.get("fantasy_id")
        )
        if rec_id is not None:
            rec_id_str = str(rec_id).strip()
            if rec_id_str and rec_id_str not in ("NA", "None", "nan"):
                # Only count as target if it's a pass play OR receiver exists
                # (some data has receiver even when pass flag missing)
                # We count it as target if play is pass or receiver exists
                # To avoid counting special-teams receivers, require
                # that play be offensive (is_pass) or have air_yards field
                # but simplest: if receiver exists, count as target
                player_targets[(rec_id_str, wk)] += 1
                team_targets[(posteam, wk)] += 1
                player_team[(rec_id_str, wk)] = posteam
                involved.add(rec_id_str)

                # air yards (may be None for dome or rush plays)
                ay = r.get("air_yards")
                if ay is None:
                    ay = 0
                try:
                    ay_f = float(ay)
                except Exception:
                    ay_f = 0.0
                player_air_yards[(rec_id_str, wk)] += ay_f
                team_air_yards[(posteam, wk)] += ay_f

                # redzone: yardline_100 <=20 (distance from opponent endzone)
                y100 = r.get("yardline_100")
                if y100 is not None:
                    try:
                        y100_f = float(y100)
                        if y100_f <= 20:
                            player_redzone_targets[(rec_id_str, wk)] += 1
                    except Exception:
                        pass

        # Carries — rusher on a run
        rush_id = r.get("rusher_player_id") or r.get("rusher_id") or r.get("rusher")
        if rush_id is not None:
            rush_id_str = str(rush_id).strip()
            if rush_id_str and rush_id_str not in ("NA", "None", "nan"):
                player_carries[(rush_id_str, wk)] += 1
                team_carries[(posteam, wk)] += 1
                player_team[(rush_id_str, wk)] = posteam
                involved.add(rush_id_str)

                y100 = r.get("yardline_100")
                if y100 is not None:
                    try:
                        y100_f = float(y100)
                        if y100_f <= 20:
                            player_redzone_carries[(rush_id_str, wk)] += 1
                    except Exception:
                        pass

        # QB / passer on dropbacks — contributes to snap count but not target/carry
        passer_id = r.get("passer_player_id") or r.get("passer_id") or r.get("passer")
        if passer_id is not None and is_pass:
            passer_str = str(passer_id).strip()
            if passer_str and passer_str not in ("NA", "None", "nan"):
                # avoid double-count if passer is also rusher (scramble)
                if passer_str not in involved:
                    # don't add to player_team unless we haven't seen them via rush/rec
                    # but for snap we still need team mapping
                    if (passer_str, wk) not in player_team:
                        player_team[(passer_str, wk)] = posteam
                    involved.add(passer_str)

        # Increment snap proxy for each involved player on this play
        for pid in involved:
            player_plays[(pid, wk)] += 1

    # Build union of all player-weeks that had any involvement
    all_keys: set[tuple[str, int]] = set()
    all_keys.update(player_targets.keys())
    all_keys.update(player_carries.keys())
    all_keys.update(player_plays.keys())

    out: list[dict] = []
    for pid, wk in sorted(all_keys):
        team = player_team.get((pid, wk), "")
        t_targets = team_targets.get((team, wk), 0)
        t_carries = team_carries.get((team, wk), 0)
        t_air = team_air_yards.get((team, wk), 0.0)
        t_plays = team_plays.get((team, wk), 0)

        p_targets = player_targets.get((pid, wk), 0)
        p_carries = player_carries.get((pid, wk), 0)
        p_air = player_air_yards.get((pid, wk), 0.0)
        p_rz_t = player_redzone_targets.get((pid, wk), 0)
        p_rz_c = player_redzone_carries.get((pid, wk), 0)
        p_plays = player_plays.get((pid, wk), 0)

        # zero-division safe shares
        target_share = (p_targets / t_targets) if t_targets else 0.0
        rush_share = (p_carries / t_carries) if t_carries else 0.0
        air_yards_share = (p_air / t_air) if t_air else 0.0
        snap_share = (p_plays / t_plays) if t_plays else 0.0
        # route_share is not directly in PBP; proxy with snap_share if available
        route_share = snap_share

        # Clamp shares to [0,1] in case of data quirks
        target_share = max(0.0, min(1.0, float(target_share)))
        rush_share = max(0.0, min(1.0, float(rush_share)))
        air_yards_share = max(0.0, min(1.0, float(air_yards_share)))
        snap_share = max(0.0, min(1.0, float(snap_share)))
        route_share = max(0.0, min(1.0, float(route_share)))

        out.append(
            {
                "player_id": pid,
                "week": wk,
                "season": season,
                "team": team,
                "targets": int(p_targets),
                "carries": int(p_carries),
                "target_share": float(target_share),
                "rush_share": float(rush_share),
                "air_yards": float(p_air),
                "air_yards_share": float(air_yards_share),
                "redzone_targets": int(p_rz_t),
                "redzone_carries": int(p_rz_c),
                "snap_share": float(snap_share),
                "route_share": float(route_share),
            }
        )

    return out


def get_pbp_features(season: int, nfl_module=None) -> list[dict]:
    """Return per-player-per-week opportunity features for a season.

    Plain list[dict] boundary — never leaks Polars. Aggregates nflreadpy
    load_pbp rows per (player_id, week) into shares. Handles zero division
    and dome temp None.

    Caching: if data/nfl_cache/pbp_{season}.json exists, load it; else call
    nflreadpy, aggregate, write cache atomically to data/nfl_cache.
    """
    # Use cache only when caller hasn't injected a mock module. Injected
    # mocks are for testing aggregation logic and should always recompute.
    if nfl_module is None:
        cached = _load_from_cache(season)
        if cached is not None:
            return cached

    nfl = nfl_module if nfl_module is not None else __import__("nflreadpy")
    frame = _call_with_retry(lambda: nfl.load_pbp(seasons=[season]))
    rows = frame.to_dicts()
    aggregated = _aggregate_pbp_rows(rows, season)

    # Write persistent cache even when a mock was injected — keeps scratch/
    # persistent in sync for backtests after the first real run. Best-effort.
    _write_cache_atomic(season, aggregated)

    return aggregated
