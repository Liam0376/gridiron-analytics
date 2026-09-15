# OSS Audit Plan — 2026-09-15

Spec: `docs/superpowers/specs/2026-09-15-oss-audit-spec.md`. Branch: `audit/oss-ready`.

- [ ] 1. Fix `test_preseason_refresh_patches_teams_and_adds_rookies` date sensitivity
  - Pin `ffanalytics.refresh.compute_nfl_week` to 1 in test (or add week 2 fixture). Keep all other asserts.
  - Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/test_refresh.py::test_preseason_refresh_patches_teams_and_adds_rookies -v`
- [ ] 2. Full suite green
  - Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` (expect 280 pass, 4 skipped)
- [ ] 3. Hub checks
  - Verify: `bash hub/verify-isolation.sh` and `cd hub && npm run check`
- [ ] 4. Docs corrections with live evidence
  - Re-verify budget + roster via Sleeper API script (not memory). Fix `docs/references/stack.md:23` branch, `docs/references/league.md:3` budget.
  - Verify: paste script output in commit message body
- [ ] 5. OSS hygiene scan
  - Verify: `git ls-files | grep -E "csv$|db$|jsonl$"` empty of third-party data; `! grep -RInE "FANTASYPROS_API_KEY\s*=\s*\S{8,}" --exclude=.env .` clean; `.env` perms 600; `hub/dist/` decision recorded
- [ ] 6. Deploy decision
  - STOP here if Liam has not confirmed a destination. Default: OSS v1 stays local-only, README/RUNBOOK activation path only. No tunnel, no Dockerfile, no host change.
  - Verify: `bash hub/start.sh --help` path works, or document why not

Commit at each checkpoint on `audit/oss-ready`. Final status DONE or DONE_WITH_CONCERNS with evidence. Restart note: no server restart needed until code changes land; hub restart needed after any `hub/` edit.
