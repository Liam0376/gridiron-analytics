# Fantasy Football Analytics — Gridiron

Personal Sleeper tool for one league ("Fantasy Bahamas", 12-team PPR auction). Not a product.

## How to work (mindset)

Marginal cost of completeness is near zero with AI. Do the whole thing, tested, documented. Never "table this for later" when the real fix is five more minutes away. Never ship a workaround when the real fix exists.

You can outsource the typing, not the understanding. Before calling anything DONE, be able to explain why the code is correct and exactly where it would break. Tests passing ≠ understanding.

## Task sizing — triage before spending tokens

Print a triage block before work on anything non-trivial:

```
Size: small | medium | large — why
Tests: local (which) | full suite — why
Branch: <name> — see "Branching"
```

- **small** — typo, copy, config tweak, one-file mechanical edit, no behavior change. No new test needed. Commit direct.
- **medium** — localized behavior change or bug fix in one module. Bug fixes still ship a regression test.
- **large** — new feature, cross-cutting change, anything judgment-heavy (model changes, scoring logic, hub contract). Full test run for every touched area, self-rating loop before calling it done.

When torn between two sizes, pick the smaller and say so. Escalate mid-task the moment scope grows. "Test what you touch" is the default; full suite only for large/contract changes.

## Branching (solo mode)

This repo runs `git config claude.mode solo` — single user, no PRs, no teammates. That means:

- No worktree ritual. Branch in place, commit, merge yourself when ready.
- Still branch for anything beyond a trivial fix — `git switch -c <slug>` off the current base — because dropping a bad change is one command (`git branch -D`) if it stays off `main`/the working branch.
- Never `git push --force` without saying so first (see Safety).
- If ever running two Claude Code sessions on this repo at once, switch to `git config claude.mode team` and use worktrees — one working tree can't safely serve two concurrent sessions.

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

## Latent vs. deterministic

If the same input always produces the same correct answer, it's deterministic work — write a script, not a model reply. Arithmetic, date math, CSV/JSON transforms, Sleeper/nflverse API calls, backtest scoring: script it. Judgment calls (is this feature worth building, does this projection look right) stay in latent space.

## Non-negotiable rules

- **Tests every time.** Small: no new test if non-behavioral. Medium/large: bug fixes ship a regression test, features ship tests in the same commit — not "later".
- **Verify every example you ship.** A command, a number, a query result you're about to hand back — run it, don't reason about it. Sleeper/nflverse data drifts week to week; don't inherit a stale claim from an earlier session.
- **Tie every change to a measurable outcome.** Backtest t-stat, projection error, a UI behavior that changes. "It works" isn't an outcome — see `docs/references/architecture.md` shadow/backtest gates.
- **Vanilla by default.** No framework-of-the-month, no dependency for what a few lines does. Check `docs/references/stack.md` before adding anything.
- **Search before building.** Stdlib/existing repo pattern first, then a real library, then custom code — and only with a documented reason.

## Completion status

- **DONE** — tests pass, evidence given, ready to use.
- **DONE_WITH_CONCERNS** — works, but flag what to watch.
- **BLOCKED** — state what's blocking, what was tried.
- **NEEDS_CONTEXT** — state exactly what's missing.

"Partially done" isn't a status.

## After every task

Commit at checkpoints (per Process above). State plainly if the dev server / hub needs a restart for the change to take effect — don't assume it's obvious.

## Confusion protocol

Stop and ask (don't guess) when: two plausible approaches to the same requirement, a request that contradicts an existing pattern (e.g. scoring/hub contracts), a destructive op with unclear scope, or missing context that changes the approach. Routine coding and obvious changes don't need this.

## Safety

- Never commit secrets (`SLEEPER_LEAGUE_ID` etc. stay in `.env`, check `.gitignore`).
- Never `rm -rf`, `git reset --hard`, `git push --force`, or drop DB tables without explicit confirmation first.
- Never skip pre-commit hooks with `--no-verify`.
- Never commit binaries or model weights — this repo is `$0 forever`.

## How Liam wants to be talked to

Direct, short, concrete. Exact file:line, not "there's an issue in the classifier". No em dashes, no AI-vocabulary padding (delve, robust, comprehensive, nuanced, leverage, seamless). If something's broken, say so plainly. End with the next action, not a recap.
