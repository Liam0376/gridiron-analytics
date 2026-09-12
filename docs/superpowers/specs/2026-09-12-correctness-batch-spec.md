# Spec: correctness batch (audit 2026-09-12)

> Status (2026-09-12): DRAFT, awaiting user confirm. No code until plan approved.

## Problems (all verified by rerun, not summary)

1. Trade dollars fabricated on small fallback. `src/ffanalytics/decision.py:596-598,634`.
   2 to 4 player comp_list still yields has_dollars True. Rate 11.43/VOR vs
   realistic 0.3 to 0.6. Repro: 59.4 VOR shown as $678.7. Fair threshold
   +-5 at `decision.py:654` mixes units.

2. Team view toss-up overflags. `hub/src/views/team.js:163` uses ceiling
   over floor (`b.upper >= s.lower`). Backend `src/ffanalytics/decision.py:380`
   uses ceiling over point (`bench_upper >= starter_pts`). Same roster shows
   more toss-ups in Team view than Start Sit API.

3. Season panel shrink mismatch. `src/ffanalytics/comparison/_model.py:329-336`
   shrinks points and stats 20 percent toward market at abs(delta) >= 51.
   `_model.py:345-374` recomputes `season_stat_deltas` raw with no shrink.
   Repro: neutral 20.0 x 17 = 340 vs market 200 gives header 312.0 but panel
   model 5100.0.

4. Hub auction mirror drift. `hub/src/lib/auctionMath.js:160,198` floors
   replacement with max(posRepl, flexRepl). Python `_auction.py:12-27` uses
   pure positional replacement. Same $ splits by two rules.

5. DST weight fallback miss. `src/ffanalytics/comparison/_auction.py:9,72`.
   `_FALLBACK_WEIGHTS` lacks K/DEF/DST and `_weighted_vor` defaults to 1.0.
   DST rows miss the 0.0 clamp path used for K/DEF.

6. Shadow loss count miscount. `src/ffanalytics/shadow.py:57` reports
   len(rows) not len(recs). First-row KeyError reports 0 rows lost for 1 input.

7. Hub qhat empty fallback divergence. `hub/server.py:169-190` returns 10.2
   on empty. `src/ffanalytics/conformal.py:15-17` raises ValueError. Same
   input, two contracts.

## Design (proposed)

- Trade: gate has_dollars on use_market, not on nonzero rate. Fallback
  small-set path reports points with `ros_dollars_are_real_dollars False`
  plus existing suffix. Fair threshold stays 5 in displayed unit.
- Team view: align frontend to backend rule (ceiling over point). One line.
- Season panel: apply same shrink_factor from `_compute_season_totals` in
  `_build_season_stat_deltas`, or pass factor in. No new math.
- Auction mirror: align hub to Python pure positional replacement, or
  document hub as display only with max drift noted. Prefer align.
- DST: add K/DEF/DST 0.0 to `_FALLBACK_WEIGHTS` path, keep clamp.
- Shadow: report len(recs) in warning. Return 0 unchanged.
- Hub qhat: mirror src contract (raise or return 5.0 default used in
  `projection.py:205`). Prefer explicit 5.0 with comment, never silent 10.2.

## Gates

- Regression tests for 1, 2, 3, 5 (small-set trade labels points, toss-up
  parity, panel equals header under shrink, warning count equals input).
- Full suite green. `hub/verify-isolation.sh` green.
- Measurable: trade fallback shows pts suffix, Team vs API toss-up count
  equal on fixture, panel header match on shrink fixture.
