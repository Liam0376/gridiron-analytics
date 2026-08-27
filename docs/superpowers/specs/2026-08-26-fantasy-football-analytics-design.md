# Fantasy Football Analytics Engine — Design Spec

## Context

Personal, single-user decision engine for one Sleeper league ("Fantasy Bahamas",
12-team, full-PPR, auction draft, 2 extra flex slots). Reuses the **architecture**
of `~/projects/sports-analytics`'s tennis-ml pipeline (Elo/Glicko w/ decay,
justified-feature discipline, conformal prediction, shadow mode, FastAPI shape,
config-as-source-of-truth) — none of the tennis-specific math. See
`docs/research/2026-data-sources.md` for the data-source decisions this spec
builds on.

## Goals

- Weekly start/sit, waiver-priority, and trade-evaluation recommendations, each
  grounded in real data and a calibrated confidence level — not a flat "start him."
- Computed in Fantasy Bahamas' **exact** scoring/roster settings, pulled live from
  Sleeper, never hardcoded.
- $0 cost forever. No paid hosting, no paid API tier, no paid DB.
- Personal CLI/local-API tool only — no public site, no other users, no ads.

## Hosting decision (deviates from the tennis-ml reference)

The reference repo targets a **public** website (Render free tier + GitHub
Pages), which forces it to deal with cold starts and free-tier sleep timers.
This project has **no public-facing requirement at all** — it's one user, on
their own always-available Mac. Running everything locally removes an entire
category of free-tier problems for free:

- **No cloud hosting.** FastAPI runs locally (`uvicorn` on `localhost`),
  invoked on demand or via a local scheduled job.
- **Scheduling:** macOS `launchd` user agent (not cron — more reliable on
  macOS, survives sleep/wake better) triggers the daily refresh job. A
  manual-refresh CLI command / endpoint is the fallback the reference repo's
  `api.py` pattern calls for, in case `launchd` doesn't fire (laptop asleep,
  closed lid) — mirrors the "scheduler can't be trusted on free hosting"
  discipline, just for a different reason (laptop uptime, not platform sleep).
- If the user later wants it reachable from their phone, that's a distinct,
  explicitly-scoped future upgrade (e.g., Tailscale to their own Mac) — out of
  scope for v1, not a paid tunnel/hosting service.

## Architecture

```
launchd (daily, in-season)  ──>  refresh job  ──>  SQLite (local file, WAL mode)
                                       │                    ^
                          ┌────────────┼────────────┐       │
                          v            v             v       │
                    nflreadpy      Sleeper API   Open-Meteo   │
                   (stats/NGS/    (league/roster/  (game-day  │
                    injuries      scoring/injury   weather)   │
                    backfill)     status)                     │
                          │            │             │        │
                          └────────────┴─────────────┴────────┘
                                       │
                                       v
                          rating + projection engine
                          (Elo/Glicko team+matchup strength,
                           conformal-calibrated projections)
                                       │
                                       v
                          FastAPI (localhost) ──> CLI / local dashboard
                                       │
                                       v
                          shadow.py-style logger (every recommendation
                          + eventual outcome, for backtesting)
```

- **Storage:** SQLite, one file (`data/fantasy.db`), WAL mode for concurrent
  read (API) + write (refresh job). Free, zero-ops, plenty for one league's
  worth of data. No Postgres needed at this scale — revisit only if multi-
  league support is ever added (out of scope now).
- **Backend:** FastAPI, in-memory cache of the current week's computed
  ratings/projections (loaded once per refresh, not re-read from SQLite per
  request) — same no-per-request-disk-I/O discipline as the reference `api.py`.
  `/health` endpoint. `/refresh` POST endpoint as the manual fallback.
- **Data ingestion:** three adapters, one per source, each isolated behind a
  narrow interface so a breaking change (especially ESPN, which has already
  broken once — its v3 base URL moved April 2024) is a one-file fix:
  - `adapters/nflverse.py` — wraps `nflreadpy` (Polars → converted to plain
    dicts/rows at the adapter boundary so Polars doesn't leak into the rest
    of the codebase).
  - `adapters/sleeper.py` — league settings, rosters, matchups, transactions,
    trending, `injury_status`.
  - `adapters/weather.py` — Open-Meteo, keyed by stadium lat/long + game time.
  - ESPN is **not** wired in v1 — the research phase confirmed nflreadpy +
    Sleeper already cover the required categories; ESPN adds unofficial-API
    risk for no data we don't already have. Documented as a future fallback
    source, not built now (YAGNI).

## Rating / matchup model

Adapted from `core/elo.py`'s discipline, not its code (tennis serve/return
math doesn't transfer):

- **Team-strength rating:** one Elo/Glicko-2 rating per NFL team, updated after
  each game (margin-of-victory-aware K-factor, like the reference), with
  Glicko's rating deviation (RD) so a rating from 2 games of data is visibly
  less certain than one from 10.
- **Positional matchup-strength rating:** per-team, per-position-group ratings
  (e.g., "run defense vs. RB," "pass defense vs. slot WR," "pass defense vs.
  TE") — same Glicko machinery, separate rating track per (team, position
  group) pair.
- **Time-decay:** rating uncertainty (RD) inflates across a bye week or a
  reported multi-week injury absence for an individual player-level rating (if
  added later) — for team/positional ratings, RD inflates with any gap between
  a team's games (bye weeks), matching the reference's inactivity-regression
  pattern.
- **Roster-fit weighting:** Fantasy Bahamas' 2 extra flex slots mean receiving
  volume at RB/WR/TE is worth more here than in a standard PPR league. This is
  applied as an explicit, documented weighting in the projection layer (not
  buried in the rating engine) — the rating engine stays league-agnostic
  (team/positional strength is a fact about the NFL, not about one league's
  roster rules); scoring/roster-context is applied only at the projection step.

## Feature selection discipline

Every feature lives in one `config.py`, annotated at the point of definition:

```python
FEATURES = {
    "target_share": {
        "status": "included",
        "why": "strongest single predictor of weekly receiving points in "
               "backtests; see docs/research/... for citation once tested",
    },
    "red_zone_touches": {
        "status": "included",
        "why": "TD probability proxy; nflreadpy doesn't expose it directly, "
               "derived from play-by-play (see adapters/nflverse.py)",
    },
    # Example of the rejection pattern this project must follow once real
    # backtesting starts:
    # "weather_wind_speed_only": {
    #     "status": "rejected",
    #     "why": "tested and REJECTED — CV evidence: no measurable lift on "
    #            "passing-yard MAE once precipitation was already in the "
    #            "model; wind alone was noise. See shadow log run 2026-XX-XX.",
    # },
}
```

No feature is added to the projection model without an entry here. No feature
is removed from `config.py` when it's rejected — the rejection and its
evidence stay, matching the reference repo's standard.

## Conformal prediction

`core/math.py`'s `conformal_qhat` pattern, adapted: instead of a bare point
projection ("14.2 fantasy points"), the projection layer produces a calibrated
interval ("14.2 ± 4.1, 80% coverage") computed from the residuals of past
projections for comparable players/weeks. This is what turns "start him" vs.
"it's close" into a real distinction — a tight interval with the flex spot's
alternative clearly outside it is a confident start; overlapping intervals is
a genuine toss-up and the tool should say so, not paper over it with a single
number.

## Shadow mode

Every recommendation the decision layer produces (start/sit, waiver priority,
trade grade) is logged to SQLite with: the recommendation, the inputs/features
that drove it, and a placeholder for the actual outcome (filled in once the
week's results are in, via the refresh job). A new heuristic (e.g., "always
start a player against a bottom-5 run defense") is not promoted into live
recommendations until it has enough logged samples to evaluate — mirrors
`MIN_MUESTRA_SHADOW`; exact minimum sample size to be set in the plan phase
once the rating engine's real output distribution is known, not guessed here.

## Decision layer

Three outputs, all reading from the same rating/projection/shadow-logged
foundation:

1. **Start/sit** — for each roster slot, rank rostered candidates by projected
   points (with conformal interval), flag the recommendation confidence as
   high (intervals don't overlap) or close (they do).
2. **Waiver priority** — rank available free agents by projected points over
   the rostered player they'd replace, weighted by Fantasy Bahamas' 2-flex
   roster shape (more start-able bodies needed at RB/WR/TE than standard).
3. **Trade evaluation** — compare projected rest-of-season value (sum of
   weekly projections, decayed by the same RD-driven uncertainty) of each
   side of a proposed trade.

Any natural-language explanation these outputs produce should explain
football-specific context (why a matchup or role matters) concisely — the
user knows fantasy strategy already, not NFL specifics.

## Error handling / data-source failure

- Sleeper or nflreadpy unreachable at refresh time → refresh job logs the
  failure, keeps serving the last successful in-memory cache, surfaces a
  visible "data stale as of [timestamp]" flag in API responses rather than
  crashing or silently serving wrong-week data.
- Open-Meteo unreachable → weather feature drops out of that week's
  projection (documented in `config.py` as a soft-fail feature, not a hard
  dependency) rather than blocking the whole refresh.

## Out of scope (v1)

- ESPN adapter (documented fallback only, not built).
- Any sport besides NFL.
- Public hosting / other users / auth.
- Real-money betting or stake-sizing logic.
- Multi-league support (single SQLite file assumes one league; revisit schema
  if that changes).
- Player-level (as opposed to team/positional) Elo ratings — noted above as a
  possible future extension, not built in v1.
