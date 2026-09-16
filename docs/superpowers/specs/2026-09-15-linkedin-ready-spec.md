# Linkedin-ready hunt Spec — 2026-09-15

Goal: no linkedin embarrassment. Fix real data bugs found by live-DB audit
and parallel code hunts (4 streams). Branch hunt/linkedin-ready.

## Live-DB findings (verified on data/fantasy.db 2026-09-15)

- BYE inflation: 389 weekly rows have opponent_team=BYE with nonzero pts (388 >0),
  sample week 7 50 BYE rows, week 11 75 etc. ROS sums them: Josh Allen
  ros=443.54 = sum of 17 weekly rows including BYE week (stat_projector.py:715
  fallback opponent BYE with 21 implied). remaining_games counts BYE weeks (17
  for Allen at week 2, true should be 16 if BYE in 2..18). Impact: every player's
  ROS inflated by ~one neutral game (~13-25 pts), trade values wrong.
- ROS stale: 707 rows, but 318 have remaining_games=1 (old 1-game ROS from seed
  or earlier incomplete refresh) alongside 389 fresh rows with 17. No season-scoped
  delete before insert in refresh.py:809-822. Weekly stale: weekly has 2..18
  (6613 rows, 17*389) missing week 1 — OK now, but no prune so past weeks persist
  as schedule rolls.
- Poisoned caches: 5 files in data/nfl_cache contain "<Mock" (ff_playerids,
  ecr_weekly_2026, rosters_weekly_2026, opportunity_2026, ngs_receiving_2026)
  from tests/test_refresh.py writes via write_json_cache (truthy Mock passes
  `if not rows` guard, json.dumps default=str stringifies).
- FP news isolation: refresh.py:997-1013 single try for trending + injuries +
  fantasypros, but fantasypros get_news raises outside try when key missing, so
  stock $0 install nukes both good fetches every refresh (news=false, 56 failures
  logged).
- Seed shadow: scripts/seed_demo.py inserts player_stats(2026,1) demo blob (545
  rows) that outranks live player_stats(2026,0) in hub queries
  ORDER BY season DESC, week DESC with week<=cw, so demo outranks live until
  week 1 passes.
- Hub contract: roster enrichment type-confused, wind always dash, interval
  chips dead, trade league_id missing — already fixed in prior fix/oss-limitations
  (trade fallback, weather join, calibration) but some remain (auction math,
  projections roster fallback).

## Fixes in this spec (P0 for linkedin)

1. BYE: compute_ros skips BYE weeks (opponent BYE → 0 pts, not summed,
   remaining_games not incremented, per_week stores 0 BYE row). Verified against
   schedule_2026.json BYE distribution (each team one BYE in 5..14).

2. ROS stale: refresh.py deletes stale ros_projections for season before
   insert (DELETE WHERE season=?), similarly weekly_projections deletes weeks <
   current_week OR weeks not in current per_week keys for season (to drop old
   BYE-inflated or past weeks). On compute failure, preserve last-good (no delete).

3. Poisoned caches: harden write_json_cache to reject non-list or Mock-like
   content (isinstance list + 0< len < 2M chars), delete poisoned files,
   regenerate via real nflreadpy fetch or on next refresh (last-good fallback
   already exists, so safe).

4. FP news isolation: split news fetches into per-source try, fantasypros
   missing key returns [] without aborting sleeper trending/injuries.

5. Seed: either store demo as week 0 with marker or make hub prefer non-demo
   source (check meta.data_source). Minimal fix: seed writes week 0 only,
   not week 1, so live week 0 refresh naturally overwrites.

Non-goals: scoring alias expansion, decision VBD off-by-one, team abbrev
canonical table unification — separate follow-up PRs (larger blast radius).

Acceptance: weekly BYE rows 0 pts, ROS = sum of non-BYE weeklies,
remaining_games = non-BYE count, poisoned files gone, news true on $0
refresh, suite green, isolation pass.
