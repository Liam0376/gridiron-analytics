# Plan: calibration honesty batch (audit 2026-09-12)

> Status (2026-09-12): DRAFT, stop for confirm. Spec: `docs/superpowers/specs/2026-09-12-calibration-honesty-spec.md`.

## Triage

```
Size: medium — copy plus thresholds plus parity, no model change, widths frozen
Tests: local (affected suites) plus full suite before commit — SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q plus hub/verify-isolation.sh
Branch: fix/calibration-honesty-batch
```

## Tasks

- [ ] 1. Branch. `git switch -c fix/calibration-honesty-batch` off implement-fantasy-football-analytics. Record `git status --short --ignored data/` baseline.
- [ ] 2. Copy honesty. Pair pooled 82 percent with by-pos table where shown. Fix `projection.py:202` comment to heuristic target. Verify: grep shows no bare 80 percent calibrated claim.
- [ ] 3. Factor parity. Canonical factors in `projection.py`, parity test across `decision.py` plus `hub/server.py`. No value change. Verify: same fixture same width all paths.
- [ ] 4. Badges plus fallback plus tiers. Drop unreachable HIGH, scale market fallback, cap tier width at 14. Tests for each. Verify: thresholds reachable, fallback equals scaled, tiers split on fixture.
- [ ] 5. Full verify. Full suite green. Isolation green. Data lines unchanged. Commit at checkpoint.

Stop. Do not implement until user confirms this plan.
