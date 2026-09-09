# Fantasy Football Analytics — Gridiron

Personal Sleeper tool for one league ("Fantasy Bahamas", 12-team PPR auction). Not a product.

## Hard constraints

- **$0 forever.** No paid tiers/hosting/DB. Surface free-tier limits. See `docs/references/stack.md`.
- **Local only.** `127.0.0.1` only — never `0.0.0.0`/tunnels without explicit ask. Outbound only to Sleeper/nflverse/Open-Meteo.
- NFL only. Single private user.

## Interface

Claude Code in this dir *is* the UI. For "who to start?" query `data/fantasy.db` or `http://127.0.0.1:8000` directly via Bash — don't send user to curl.

## Process

1. Research → 2. Spec `docs/superpowers/specs/` → 3. Plan `docs/superpowers/plans/` (checkboxes + verify) → stop for confirm → implement task-by-task, commit at checkpoints. Rejected features → `# REJECTED — evidence: ...` inline.

## Stack

Python >=3.12, `.venv/bin/python`, `SLEEPER_LEAGUE_ID` required. `FFANALYTICS_DB_PATH` overrides `data/fantasy.db`. No lint/CI in repo.

## Further Reading

**IMPORTANT:** Before any task, read relevant docs below first. Load full context before editing.

- `docs/references/stack.md` — env, commands, gotchas (tests, dev server, isolation `hub/verify-isolation.sh`)
- `docs/references/architecture.md` — engineering discipline + model/hub architecture + shadow/backtest gates
- `docs/references/league.md` — roster/scoring (Sleeper source of truth, bonuses, FAAB, Reglamento)
- `docs/reglamento-2026.md` — official rules, never hardcode scoring
- `hub/DESIGN.md` + `hub/README.md` — hub isolation contract
- `docs/research/2026-data-sources.md` — data source comparison
