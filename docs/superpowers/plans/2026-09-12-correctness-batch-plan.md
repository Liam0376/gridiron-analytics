# Plan: correctness batch (audit 2026-09-12)

> Status (2026-09-12): DRAFT, stop for confirm. Spec: `docs/superpowers/specs/2026-09-12-correctness-batch-spec.md`.

## Triage

```
Size: large — cross-cutting (decision, comparison, hub, shadow), judgment on units plus hub contract
Tests: full suite — SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q plus hub/verify-isolation.sh
Branch: fix/correctness-audit-batch — see Branching (solo mode)
```

## Tasks

- [ ] 1. Branch. `git switch -c fix/correctness-audit-batch` off current base. Verify `git status --short --ignored data/` matches audit baseline (`M data/nfl_cache/schedule_2026.json` only).
- [ ] 2. Trade dollar gate. `decision.py:596-654`. Gate on use_market. Add regression test small fallback reports pts not $. Verify: fixture 2-for-1 shows `ros_dollars_are_real_dollars False` plus suffix.
- [ ] 3. Team toss-up parity. `hub/src/views/team.js:163` to ceiling over point. Add hub fixture test or manual fixture diff. Verify: Team count equals API count.
- [ ] 4. Season panel shrink. `_model.py:345-374` apply shrink_factor. Add regression test 340 vs 200 case. Verify: header 312.0 equals panel total.
- [ ] 5. Auction mirror plus DST. `auctionMath.js:160,198` plus `_auction.py:9,72`. Add tests for DST weight 0 and replacement parity. Verify: same fixture same $.
- [ ] 6. Shadow count plus hub qhat. `shadow.py:57` len(recs). `hub/server.py:169-190` explicit default. Add tests. Verify: warning count equals input, empty qhat contract documented.
- [ ] 7. Full verify. `SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q` green. `bash hub/verify-isolation.sh` green. `git status --short --ignored data/` data lines unchanged. Commit at checkpoint.

Stop. Do not implement until user confirms this plan.
