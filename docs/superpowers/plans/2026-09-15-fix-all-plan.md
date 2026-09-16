# Fix-all Plan — 2026-09-15 (branch fix/oss-limitations)

Spec: `docs/superpowers/specs/2026-09-15-fix-all-spec.md`.

- [ ] 1. Trade fallback
  - Add route + `handle_trade` in `hub/server.py`. Regression test in `tests/test_hub_server.py`.
  - Verify: `SLEEPER_LEAGUE_ID=test .venv/bin/pytest tests/test_hub_server.py -q`, `bash hub/verify-isolation.sh`
- [ ] 2. Weather slate join
  - Vendor coords map + join in `handle_matchups`. Test seeds weather rows. Update `hub/README.md` weather lines.
  - Verify: same as above + slate wind equals seeded value
- [ ] 3. Calibration
  - Measure script (temp file, not committed) recomputes 2025 coverage at candidate factors. Ship smallest fix + version bump + artifact note.
  - Verify: `pytest tests/test_conformal.py tests/test_interval_parity.py -q`, full suite
- [ ] 4. Seed verify
  - Verify: `SLEEPER_LEAGUE_ID=test` seed into temp DB green
- [ ] 5. Full suite + isolation, commit per fix, merge to master on approval

No server restart needed until merge; hub restart needed after merge for `hub/` edits, model restart for factor changes.
