# Backend Audit

Date: 2026-09-15
Agent: Backend

## Scope

API/server code, error handling, caching, refresh jobs, test coverage.

## Findings

### B1: Test coverage is good (256 pass, 4 skip)

Full suite passes. Coverage areas:
- refresh.py: team patching, xwalk, rookies, matchup clobber, opportunity features, props pruning
- scoring.py: stat mapping, NaN guards, flex adjustment
- stat_projector.py: weighted avg, TD regression, usage trend, Vegas, weather, conformal bounds
- decision.py: start/sit, waiver, trade, VBD auction
- projection.py: interval calculation
- shadow.py: log/resolve
- hub/server.py: API routing
- api.py: integration-level tests (skipped without RUN_INTEGRATION=1)

### B2: NaN propagation guards exist (Clean)

scoring.py:77-99 guards NaN/Inf in stat values and multipliers.
refresh.py:676-678 guards NaN/Inf in projected_points.
stat_projector.py:555-567 _safe_float pattern in build_game_context.
api.py and hub/server.py both have NaN guards in scoring paths.

### B3: refresh_log audit trail fixed in Audit 22.0 (Clean)

refresh.py:43-51 _log() no longer auto-commits. Entries commit with the caller's
transaction, so refresh_log says "success=1" only when the data actually wrote.

### B4: JSON cache write uses default=str (Clean)

refresh.py:113 write_json_cache uses `json.dumps(rows, default=str)` to handle
non-JSON types (datetime.date from roster birth_date). Test exists:
test_write_json_cache_survives_date_objects.

### B5: No scoring path test for 40+ bonuses with stat_projector output (Medium)

scoring.py maps `passing_40 -> pass_cmp_40p` etc. but stat_projector.py does NOT
project 40+ yard play stats. These stats are only available in actual game data.
For projections, the 40+ bonus contribution is always 0.

Impact: Projected points systematically underestimate for players who frequently
produce 40+ yard plays. This is a known model limitation (the bonus is rare and
noisy, hard to project). But the underestimation is consistent, so relative
rankings are unaffected.

### B6: STORE-ON-SUCCESS pattern correct (Clean)

refresh.py:960-1096 checks `status.get("sleeper")` etc. before each INSERT.
Failed sources preserve last-good data. Pattern is consistent across all tables.

### B7: Thread-local DB connection pattern (Clean)

db.py uses threading.local() for per-request connections. reset_conn() in api.py
middleware closes at request teardown. FastAPI sync workers get one connection per thread.

### B8: Missing test for interval factor parity (Medium)

projection.py and decision.py both define POS_WIDTH_FACTORS and INTERVAL_FACTORS_VERSION.
No test verifies they match. A test should assert:
```python
from ffanalytics.projection import POS_WIDTH_FACTORS as P_FACTORS, INTERVAL_FACTORS_VERSION as P_VER
from ffanalytics.decision import POS_WIDTH_FACTORS as D_FACTORS, INTERVAL_FACTORS_VERSION as D_VER
assert P_FACTORS == D_FACTORS and P_VER == D_VER
```
