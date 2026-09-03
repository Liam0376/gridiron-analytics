import os
from datetime import datetime, timedelta
from pathlib import Path

LEAGUE_ID = os.environ["SLEEPER_LEAGUE_ID"]
if not LEAGUE_ID:
    raise RuntimeError(
        "SLEEPER_LEAGUE_ID env var must be set — this project never "
        "hardcodes league settings, see CLAUDE.md"
    )

DB_PATH = Path(os.environ.get("FFANALYTICS_DB_PATH", "data/fantasy.db"))

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
STARTER_BUDGET_POOL = 2352.0


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
