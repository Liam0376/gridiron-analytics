# Spec: docs plus backup batch (audit 2026-09-12)

> Status (2026-09-12): DRAFT, awaiting user confirm. Docs plus one backup line. No model change.

## Problems (verified, low severity)

1. League docs sourcing. `docs/references/league.md:5` adds week 11
   deadline plus FAAB $100 2-day clear with no source in reglamento.
   Sleeper settings are truth per league.md; cite fetch command instead.
   Budget stays $200, no change.

2. Font docs conflict. `hub/README.md:97` says Instrument Sans plus
   JetBrains Mono. `hub/DESIGN.md:81` mandates Helvetica/SF zero webfonts.
   Code follows DESIGN (`tokens.css:26`).

3. Stale claims. `docs/references/stack.md:12` says 204 tests, suite is
   225. `stack.md:17` claims /private/tmp fallback, `adapters/pbp.py:19-26`
   is persistent only. `docs/RUNBOOK.md:188` says DB path accepts any path,
   allowlist ships in `config.py:50-55` plus `hub/server.py:209-247`.
   `hub/README.md:90` promises exact curl in empty states, zero curl
   strings in `hub/src` empty states. `hub/README.md:67` chips
   VALUE/TRACKING/NO EDGE have zero hits in `hub/src`.

4. Backup gap. `scripts/refresh_job.sh:1-34` plus plist have no backup step.
   Only copy is `data/fantasy.db.bak-20260904-headshot`, 8 days stale at
   audit. `docs/RUNBOOK.md:164-172` documents manual drill, no log it ran.
   Risk is annoyance (rebuild from refresh), not outage.

5. Secrets scan never fails. `.github/workflows/ci.yml:39`
   continue-on-error plus `|| true` fallback. No pre-commit config,
   `.git/hooks/` samples only.

6. Audit trail drift (docs only, no value change). `stat_projector.py:55`
   XGB val wording vs `xgb_meta.json:49` vs `backtest_ml_results.json:86`.
   Freeze n 10351 vs artifacts 10706. Snap t 1.66 vs stored 13.69/15.06.
   Production stays REJECTED either way.

## Design (proposed)

- league.md: keep $200. Flag week 11/FAAB as Sleeper settings with fetch
  command, not reglamento claims.
- README fonts to DESIGN. README chips to shipped copy or remove.
  README empty states to real copy (no curl) or add curl to UI.
  stack.md counts plus cache quirk plus RUNBOOK DB TODO updated.
- refresh_job.sh: append pre-refresh `.backup` to dated file plus keep
  last 7. Log one drill run.
- CI: scan fails build on secret hit, or document why non-blocking.
  Add pre-commit config only if cheap.
- stat_projector header: correct XGB val pointer, note n delta source,
  reconcile snap t numbers or mark artifact superseded. REJECTED stands.

## Gates

- Grep checks for each stale claim gone.
- Backup line runs without breaking refresh lock path.
- Full suite green. No DB writes beyond backup file.
