# Spec: calibration honesty batch (audit 2026-09-12)

> Status (2026-09-12): DRAFT, awaiting user confirm. Widths stay frozen. No retuning.

## Problems (all verified by rerun)

1. Pooled 82 percent masks K. `data/models/coverage_2025.json:20-29`.
   Displayed overall 82.08 percent hides K 58.61 percent, 21.4pp below
   80 percent target. Raw QB 58.14 percent already documented. Any UI
   or doc that presents pooled 82 percent as calibrated misleads.

2. Label slip. `src/ffanalytics/projection.py:202` comment says 80 percent
   confidence interval. Contradicts `conformal.py:1-10` plus
   `projection.py:186-187` heuristic not calibrated disclaimer.

3. Triplicated factors. `projection.py:191`, `decision.py:334`,
   `hub/server.py:1595` repeat QB 1.45 K 0.55 plus point factor
   `min(1.60,1+(pts-12)*0.022)` clamp 3-14. Three mints drift.

4. ConfBadge HIGH unreachable. `hub/src/components/badges.js:20` HIGH
   needs w < 3. Clamp min is 3.0 in all three interval paths, so label
   promises precision the scale never emits.

5. Market fallback bypass. `hub/src/views/projections.js:117-119` uses
   fixed +-2.5 width 5.0 for market-only rows, bypassing pos/point
   scaling. Same page draws narrower bands for unknown players than
   for calibrated peers.

6. Tier overmerge. `hub/src/views/tierlists.js:50` season width x sqrt(9)
   unclamped, then `hub/src/tierlist.js:11` effGap max(gap, 0.7*medianWidth)
   inflates and hides real gaps.

## Design (proposed)

- Docs plus UI copy: pooled numbers always paired with by-pos table.
   K rows labeled narrow by design, not calibrated. No width change.
- Fix comment at `projection.py:202` to heuristic 80 percent target.
- Single source for factors: keep `projection.py` canonical, have
   `decision.py` plus `hub/server.py` import or copy with version
   comment plus parity test. No value change.
- Badges: drop HIGH or set threshold to w <= 3.0 equals MED. Prefer
   drop HIGH, keep MED/WIDE.
- Market fallback: apply same pos/point scaling with clamp, or label
   fallback band as uncalibrated. Prefer scale plus label.
- Tiers: cap width at 14 before median, same clamp as intervals.

## Gates

- Copy checks: pooled never shown without by-pos nearby.
- Unit tests: badge thresholds reachable, fallback width equals scaled,
   tier cap respected, factor parity across three paths.
- Full suite green plus isolation. Widths byte identical on fixture.
