import os
from datetime import datetime, timedelta
from pathlib import Path

LEAGUE_ID = os.environ.get("SLEEPER_LEAGUE_ID", "")
# why .get + no raise at import: the hub is multi-league now — league id
# arrives per-request (UI setup screen / ?league_id= / POST /refresh body).
# Import-time raise broke every tool/consumer without the env var (and masked
# the friendly message behind KeyError). Refresh paths raise a clear
# RuntimeError at call time instead (see get_league_id).


def get_league_id(override: str | None = None) -> str:
    """Resolve the active Sleeper league id: explicit arg > env > "".

    Returns "" when unconfigured (callers decide: 503/empty-state, never crash).
    """
    if override and str(override).strip():
        return str(override).strip()
    return (LEAGUE_ID or "").strip()


def require_league_id(override: str | None = None) -> str:
    """get_league_id or raise the friendly error (refresh paths only)."""
    lid = get_league_id(override)
    if not lid:
        raise RuntimeError(
            "SLEEPER_LEAGUE_ID env var must be set (or pass league_id) — "
            "copy .env.example to .env and paste your Sleeper league ID"
        )
    return lid


def is_valid_league_id(lid: str | None) -> bool:
    """Sleeper league ids are numeric strings (also guards ?league_id= input)."""
    return bool(lid) and str(lid).isdigit()


DB_PATH = Path(os.environ.get("FFANALYTICS_DB_PATH", "data/fantasy.db"))


def db_path_for_league(league_id: str | None = None) -> Path:
    """DB file for a league. Default/env league keeps legacy data/fantasy.db
    (backward compat with existing installs); any other league gets
    data/fantasy_<id>.db. Explicit FFANALYTICS_DB_PATH always wins.
    why per-league files (not a league_id column): zero-migration multi-league —
    each league is an isolated snapshot with identical schema; the hub proxy
    allowlists data/ so ?league_id= can only resolve inside it.
    """
    if "FFANALYTICS_DB_PATH" in os.environ:
        p = Path(os.environ["FFANALYTICS_DB_PATH"]).resolve()
        allowed = Path("data").resolve()
        if not str(p).startswith(str(allowed) + os.sep) and p.parent != allowed:
            raise ValueError(f"FFANALYTICS_DB_PATH must be inside data/: {p}")
        return p
    lid = get_league_id(league_id)
    default_lid = (LEAGUE_ID or "").strip()
    if not lid or (default_lid and lid == default_lid):
        return Path("data/fantasy.db")
    if not is_valid_league_id(lid):
        raise ValueError(f"invalid league id: {lid!r}")
    return Path(f"data/fantasy_{lid}.db")

# Every feature the projection engine uses is declared here with why it's
# in, or (once tested) why it was rejected. See docs/superpowers/specs/
# 2026-08-26-fantasy-football-analytics-design.md#feature-selection-discipline
FEATURES = {
    "target_share": {
        "status": "included",
        "why": "strongest single predictor of weekly receiving points; "
               "to be confirmed against real backtests once shadow data "
               "accumulates",
    },
    "snap_pct": {
        "status": "included",
        "why": "proxy for role/opportunity independent of target share; "
               "catches role changes before target share reflects them",
    },
    "opponent_positional_rating": {
        "status": "included",
        "why": "core defense-adjustment signal — see rating engine in "
               "the design spec",
    },
}

# Minimum logged+resolved shadow samples before a new heuristic can be
# promoted to a live recommendation. Starting value only — revisit once
# real recommendation volume/variance is known (mirrors reference repo's
# MIN_MUESTRA_SHADOW, which was tuned empirically, not guessed).
MIN_SHADOW_SAMPLES = 20

# Flex-league scarcity adjustment: leagues with 2+ flex slots increase
# demand for RB/WR/TE, making receiving volume more valuable.
# tested and REJECTED: higher multipliers (1.10+) — overcorrected in
# backtesting against standard PPR rankings; 1.05 is conservative start.
FLEX_SCARCITY_MULTIPLIER = 1.05

# Weather effect on projections (points deducted per mph of wind)
# Affects QB, WR, K positions. Conservative start — revisit with shadow data.
WEATHER_WIND_PENALTY_PER_MPH = 0.02

def get_feature_status(name: str) -> str:
    return FEATURES[name]["status"]


def get_current_nfl_season() -> int:
    from datetime import datetime
    return datetime.now().year


# Max season with published nflverse weekly player stats.
# why: in preseason (e.g. Sep 2026 before Week 1 kicks off) live nflreadpy has
# no 2026 weekly rows yet, so unclamped stats_season=2026 makes refresh log
# nflverse/ratings failures by design (2/5 red). Clamping to the last complete
# season keeps refresh green; bump to 2026 once Week 1 stats publish.
# tested and REJECTED: probing nflreadpy at import to auto-detect max season —
# adds network I/O to config import (breaks offline unit tests + cold start).
MAX_STATS_SEASON = 2025


def get_stats_season() -> int:
    from datetime import datetime
    now = datetime.now()
    computed = now.year if now.month >= 9 else now.year - 1
    # why: clamp to last season with published data (see MAX_STATS_SEASON).
    return min(computed, MAX_STATS_SEASON)


# Replacement-level starters used by VBD/VOR auction math. 12-team full-PPR with
# 2 FLEX slots: QB 1*12=12, RB 2*12 + flex share = 28, WR 2*12 + flex share = 32,
# TE 1*12=12, K/DEF streamed at $1 in practice but VBD still allocates 12 each
# before clamping.
POS_REPL_COUNTS = {"QB": 12, "RB": 28, "WR": 32, "TE": 12, "K": 12, "DEF": 12}
# Empirical fallback for positional scarcity weights when market/model share is
# too thin to derive a weight. K/DEF streamed at $1 -> weight 0.
POS_WEIGHT_FALLBACK = {"QB": 0.65, "RB": 1.10, "WR": 0.92, "TE": 0.78, "K": 0.0, "DEF": 0.0}

# 12-team $200 auction pool ($2400) minus 48 bench spots at $1 each = $2352
# starter budget (10 starters * 12 teams). Aligned with auction.js / vbdAuction.js.
# NOTE: both constants below are the 12x$200 DEFAULTS kept for backward compat
# (tests, cold-start fallbacks). Live code must prefer league_economics(), which
# derives the same numbers from any league's roster/teams/budget.
STARTER_BUDGET_POOL = 2352.0


def league_economics(
    total_rosters: int = 12,
    roster_positions: list | None = None,
    auction_budget: int | float = 200,
) -> dict:
    """Per-league auction economics derived from league settings + draft info.

    Returns {teams, budget, starters_per_team, bench_per_team, flex_slots,
    starter_pool, starter_slots_total, bench_slots_total, repl_counts,
    pos_starter_slots}. For the reference 12-team 2-FLEX $200 league this
    reproduces POS_REPL_COUNTS / STARTER_BUDGET_POOL exactly.

    Methodology (preserved from the 12-team tuning, audit 2026-09-01):
    base starters per position x teams; FLEX extra goes to the positions
    actually flexed — RB +F/6, WR +F/3, TE +0 (TEs are ~never flexed over
    RB/WR); QB/K/DEF get no flex share. Bench spots cost $1 each.
    Flex-split ratios are starting values — revisit with shadow data.
    """
    teams = max(1, int(total_rosters or 12))
    budget = float(auction_budget or 200)
    positions = list(roster_positions or [])
    bench = sum(1 for p in positions if p == "BN") or 4
    flex = sum(1 for p in positions if p == "FLEX")
    starters = (len(positions) - bench) if positions else 10
    starters = max(1, starters)

    def _base(pos: str, fallback: int) -> int:
        return sum(1 for p in positions if p == pos) if positions else fallback

    rb_base, wr_base = _base("RB", 2), _base("WR", 2)
    repl_counts = {
        "QB": teams * _base("QB", 1),
        "RB": round(teams * (rb_base + flex / 6)),
        "WR": round(teams * (wr_base + flex / 3)),
        "TE": teams * _base("TE", 1),
        "K": teams * _base("K", 1),
        "DEF": teams * _base("DEF", 1),
    }
    bench_total = teams * bench
    return {
        "teams": teams,
        "budget": budget,
        "starters_per_team": starters,
        "bench_per_team": bench,
        "flex_slots": flex,
        "starter_pool": teams * budget - bench_total * 1,
        "starter_slots_total": teams * starters,
        "bench_slots_total": bench_total,
        "repl_counts": repl_counts,
        "pos_starter_slots": {
            "QB": _base("QB", 1), "RB": rb_base, "WR": wr_base,
            "TE": _base("TE", 1), "K": _base("K", 1), "DEF": _base("DEF", 1),
        },
    }


def compute_nfl_week(now: datetime | None = None) -> int:
    """Approximate NFL week (1-18) for a given date.

    Season starts the Monday after Labor Day (first Monday in September).
    Preseason returns 1 (unified with hub/server.py compute_nfl_week which
    never returns 0 — callers already do max(1, week) / target_wk fallbacks,
    so returning 0 only forced every consumer to special-case it).
    In-season clamps to 1..18. For logging only.
    """
    if now is None:
        now = datetime.now()
    september_first = datetime(now.year, 9, 1)
    offset_to_monday = (0 - september_first.weekday()) % 7
    labor_day = september_first + timedelta(days=offset_to_monday)
    season_start = labor_day + timedelta(days=7)
    if now < season_start:
        # why: hub returns 1 preseason; config returned 0 caused divergence
        # (refresh rating_weeks range(1,19) vs hub week-1 assumptions).
        # tested and REJECTED: keeping 0 + documenting divergence — every
        # caller already branches on 0, so unifying to 1 removes dead code.
        return 1
    days_since = (now - season_start).days
    week_num = days_since // 7 + 1
    if week_num < 1:
        return 1
    if week_num > 18:
        return 18
    return week_num
