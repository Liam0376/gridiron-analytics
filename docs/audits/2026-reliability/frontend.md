# Frontend / Hub Audit

Date: 2026-09-15
Agent: Frontend / Hub

## Scope

Whether the hub shows numbers honestly per hub/DESIGN.md.

## Findings

### H1: Uncertainty display (Clean)

hub/README.md:58 documents interval bars showing "low - point - high".
The bar uses model range with half-width scale. Overlap noted as "toss-up,
not a statistical test." Honest framing.

### H2: Stale-data indicator exists (Clean)

hub/README.md:91 documents staleness dot (cold/warm). API-down degrades to
last DB snapshot with visible indicator.

### H3: Correct week display (Clean)

Hub uses compute_nfl_week() (hub/server.py vendored version). Both config.py
and hub/server.py return 1 for preseason (unified in recent commits).

### H4: Vendored scoring in hub/server.py (Medium, D5)

hub/server.py:60-69 has its own DEFAULT_SCORING copy. This must be manually
kept in sync with src/ffanalytics/scoring.py:7-19.

Current state: both copies match (verified by inspection, same key-value pairs).
Risk: divergence if one is updated without the other.

architecture.md now allows hub to import ffanalytics. This vendoring is
technical debt but not a current correctness issue. See DECISIONS.md D5.

### H5: Interval factors duplicated in hub (Low)

hub/server.py likely has its own interval calculation. The factors must match
projection.py. Decision D6 applies.

### H6: Weather badges show placeholder (Known, documented)

hub/README.md:87 explicitly documents this. Not a bug, just incomplete data.

### H7: Rounding or sorting bugs (Not found)

Hub sorts by projected_points. No evidence of rounding bugs affecting rankings.
The mono font for numbers (SF Mono per DESIGN.md) ensures consistent alignment.
