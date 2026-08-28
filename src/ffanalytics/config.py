import os
from pathlib import Path

LEAGUE_ID = os.environ.get("SLEEPER_LEAGUE_ID")
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

def get_feature_status(name: str) -> str:
    return FEATURES[name]["status"]
