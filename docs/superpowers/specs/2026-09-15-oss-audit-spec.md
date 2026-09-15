# OSS Audit Spec — 2026-09-15

Goal: audit, test, debug, verify Gridiron so it is ready to deploy as an open source fantasy football hub. Stay `$0 forever`, local-only `127.0.0.1` unless Liam approves a destination.

## Baseline evidence (verified 2026-09-15)

- Branch `master`, clean tree, log head `8820bda`.
- `SLEEPER_LEAGUE_ID=test pytest -q`: 279 pass, 1 fail, 4 skipped.
  Fail: `tests/test_refresh.py:433` `test_preseason_refresh_patches_teams_and_adds_rookies`, `assert 'BYE' == 'KC'`.
  Root cause: test mocks schedule week 1 only (`test_refresh.py:393`), but `refresh.py:607` uses live `compute_nfl_week()`. Today 2026-09-15 Tue gives week 2 (`config.py:247`), so `stat_projector.py:715` falls back to `opponent BYE`. Date-sensitive test, not production bug.
- `bash hub/verify-isolation.sh`: pass, exit 0.
- Secrets: CI `secrets-scan` present (`.github/workflows/ci.yml`). Local `.env` is `600`, gitignored. No `FantasyPros_*.csv` tracked (`git ls-files` clean). `data/*.db*`, `data/nfl_cache/`, `data/ml/*.jsonl`, `logs/` gitignored. `DATA_NOTICE.md` covers code-only MIT.
- Live DB `data/fantasy.db`: 19 tables, `player_stats 3`, `ros 707`, `weekly 6613`, `market 2`, last refresh success `2026-09-15T16:07`. Preseason thin stats expected.
- League truth from DB: Fantasy Bahamas, auction budget 200, roster QB RB RB WR WR TE FLEX FLEX K DEF BNx4, FAAB 100, deadline week 11.

## Doc mismatches found

- `docs/references/stack.md:23` says branch `implement-fantasy-football-analytics`, actual `master`.
- `docs/references/league.md:3` says $250 budget, DB draft settings say 200. DB wins until re-verified via Sleeper API.
- Architecture note `docs/references/architecture.md:31` says isolation lifted, but `hub/verify-isolation.sh` still passes and CI no longer gates. Keep script optional, do not delete.

## OSS gaps to close

1. Fix date-sensitive test by pinning week (patch `compute_nfl_week` in test). Regression test ships in same commit.
2. Correct stack.md branch + league.md budget after live Sleeper re-verify. Verify, do not reason.
3. OSS deploy story: repo is local-only by design (`RUNBOOK.md`, `CONTRIBUTING.md`). No Dockerfile, no tunnel docs. Decide: OSS v1 stays local-only with `<10min` warm board activation, or add explicit deploy target after Liam confirms destination.
4. Hardcoded league ID uses are safe (tests, docs, `scoring.py:4` comment fallback, `hub/src/views/setup.js:63` placeholder). No code default leaks private league. Confirm no other PII in `hub/dist/` (built file contains ID string, rebuild after cleanup if needed).
5. `FantasyHub.app/` macOS wrapper stays as-is per `CONTRIBUTING.md`. `hub/dist/` is build output, check if it should stay gitignored for OSS.

## Non-goals

- No new model logic, no scoring changes, no hub contract changes.
- No lockfile (intentional per `CONTRIBUTING.md:67`).
- No history rewrite for LFS/data (leave history alone per README).
- No `api.py` / `server.py` patches from OSS side (ownership boundary in `CONTRIBUTING.md:20`).

## Acceptance

- `SLEEPER_LEAGUE_ID=test pytest -q` green.
- `bash hub/verify-isolation.sh` green.
- `cd hub && npm run check` green (add if missing from CI).
- Docs corrected with verified numbers.
- Status DONE with evidence, or DONE_WITH_CONCERNS with watch items.
