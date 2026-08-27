# Fantasy Football Analytics Engine

Personal, single-user analytics tool for one Sleeper league ("Fantasy Bahamas",
12-team full-PPR auction). Not a product, not for sale, no public deployment.

## Hard constraints

- **$0 cost, forever.** No paid tiers, no cards-on-file trials, no paid hosting/DB.
  Flag free-tier limits (rate limits, quotas, cold starts) explicitly instead of
  assuming they're fine.
- No monetization, no public site, no other users.
- NFL/fantasy football only — no other sports.
- No real-money betting/staking logic.

## Engineering discipline (reused from `~/projects/sports-analytics` tennis-ml)

Reference implementation: `~/projects/sports-analytics/.claude/worktrees/tennis-analytics-web/backend/`
(tennis ATP/WTA pipeline — sport-specific math is NOT reusable, architecture is):

- `core/elo.py` — Elo/Glicko rating engine w/ time-decay, K-factor decay,
  inactivity regression, explicit uncertainty (RD). Adapt → team-strength /
  positional matchup-strength ratings.
- `config.py` — every feature justified inline; rejected features documented
  with the CV evidence that killed them, not deleted silently.
- `core/math.py` (`conformal_qhat`) — conformal prediction for calibrated
  confidence, not bare point projections.
- `shadow.py` / `evaluacion.py` — log every new rule/model change and backtest
  against real outcomes before it's trusted live. `MIN_MUESTRA_SHADOW` pattern.
- `api.py` — small FastAPI surface, in-memory artifact cache (no per-request
  disk I/O), `/salud`-style health endpoint, manual-refresh fallback endpoint.
- Config-as-single-source-of-truth — one file, every constant commented with
  its origin. No magic numbers scattered through the codebase.

Match the reference repo's comment discipline: a rejected feature/heuristic gets
`# tested and REJECTED — evidence: ...` inline, not silent deletion.

## League specifics (verify programmatically via Sleeper API, don't hardcode)

Sleeper, 12 teams, auction draft, full PPR. Roster: 1 QB / 2 RB / 2 WR / 1 TE /
2 FLEX(WR-RB-TE) / 1 K / 1 DEF, 4 bench, 2 IR. Two extra flex slots vs. standard
league → receiving volume at RB/WR/TE worth more here than generic PPR rankings
assume. Pull exact scoring settings from Sleeper API and verify against league
notes each season (scoring can be edited).

User is experienced at fantasy sports generally, new to NFL specifics — any
NL output should explain football context concisely, not fantasy fundamentals.

## Process

1. Research phase — current free data source status, written comparison.
2. Spec phase — `docs/superpowers/specs/`, mirrors reference repo style.
3. Plan phase — `docs/superpowers/plans/`, checkboxes + verification steps.
4. Stop for user confirmation before implementation.
5. Implement task-by-task, commit at checkpoints.
