# Fantasy Football Analytics Engine

Personal, single-user analytics tool for one Sleeper league ("Fantasy Bahamas",
12-team full-PPR auction). Not a product, not for sale, no public deployment.

## Hard constraints

- **$0 cost, forever.** No paid tiers, no cards-on-file trials, no paid hosting/DB.
  Flag free-tier limits (rate limits, quotas, cold starts) explicitly instead of
  assuming they're fine.
- **Fully local. No cloud, no public exposure, ever.** FastAPI binds
  `127.0.0.1` only — never pass `--host 0.0.0.0` or open a port/tunnel to the
  internet without the user explicitly asking. Data ingestion still makes
  outbound calls to free public APIs (Sleeper, nflreadpy, Open-Meteo) — that's
  unavoidable (real recommendations need real data) and carries zero charge
  risk (no auth/card anywhere), but it's the only "web" involved. No inbound
  exposure, no hosting, no deploy step, ever.
- No monetization, no public site, no other users.
- NFL/fantasy football only — no other sports.
- No real-money betting/staking logic.

## Primary interface: ask Claude directly

The user does not want to build/run a separate CLI or dashboard to query
this. **Claude Code, working in this project directory, is the interface.**
When the user asks "who should I start this week" or similar, query the
local SQLite DB (`data/fantasy.db`) and/or call the local API directly via
Bash — don't tell the user to go run a curl command themselves. Treat every
recommendation question as "read the project's current data and answer,"
the same as reading any other file in this repo.

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

## League specifics (verify programmatically via Sleeper API, don't hardcode — official Reglamento 2026 at ~/Downloads/Reglas\ Fantasy\ Bahamas.md)

Sleeper ID `1397736035240173568`, 12 teams, auction draft ($250 budget), full PPR (`rec=1.0`). Roster: 1 QB / 2 RB / 2 WR / 1 TE /
2 FLEX(WR-RB-TE) / 1 K / 1 DEF, 4 bench + 2 IR via `settings.reserve_slots=2` (IR not in `roster_positions`; Sleeper returns `['QB','RB','RB','WR','WR','TE','FLEX','FLEX','K','DEF','BN','BN','BN','BN']` + `reserve_slots=2`). Two extra flex slots vs. standard
league → receiving volume at RB/WR/TE worth more here than generic PPR rankings
assume. Pull exact scoring settings from Sleeper API and verify against league
notes each season (scoring can be edited — includes 40+ bonuses `pass_cmp_40p/rush_40p/rec_40p=1.0`, `pass_td_40p/rec_td_40p/rush_td_40p=1.0`, `fgm_*/fgmiss`, `fum_lost=-2.0`, etc.). Trades: deadline week 11, 2-day review, majority vote (6 needed, involved managers excluded per Reglamento); waivers: FAAB $100, 2-day clear. Entry $750 MXN, prizes $5,500/$2,500/$1,000.

User is experienced at fantasy sports generally, new to NFL specifics — any
NL output should explain football context concisely, not fantasy fundamentals.

## Process

1. Research phase — current free data source status, written comparison.
2. Spec phase — `docs/superpowers/specs/`, mirrors reference repo style.
3. Plan phase — `docs/superpowers/plans/`, checkboxes + verification steps.
4. Stop for user confirmation before implementation.
5. Implement task-by-task, commit at checkpoints.
