# Plan: docs plus backup batch (audit 2026-09-12)

> Status (2026-09-12): DRAFT, stop for confirm. Spec: `docs/superpowers/specs/2026-09-12-docs-backup-spec.md`.

## Triage

```
Size: small — docs plus one shell line plus CI flag, no behavior change except backup side file
Tests: local (full suite once) — SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q plus hub/verify-isolation.sh
Branch: fix/docs-backup-batch
```

## Tasks

- [ ] 1. Branch. `git switch -c fix/docs-backup-batch` off implement-fantasy-football-analytics. Record data status baseline.
- [ ] 2. Docs. league.md, README fonts/chips/empty states, stack.md counts plus cache, RUNBOOK DB TODO, stat_projector header pointers. Verify: grep each claim.
- [ ] 3. Backup. Append dated `.backup` plus prune to refresh_job.sh. One manual drill run logged. Verify: backup file appears, refresh still exits 0.
- [ ] 4. CI. Make scan fail on hit or document non-blocking reason. Verify: workflow diff minimal.
- [ ] 5. Full verify. Full suite green. Isolation green. Commit.

Stop. Do not implement until user confirms.
