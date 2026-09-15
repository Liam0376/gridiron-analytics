# Fantasy Football Expert Audit

Date: 2026-09-15
Agent: Fantasy Football Expert

## Scope

Judged model outputs against real football context for 2026 Week 1.
Cross-checked against Hashtag Football tools (manual only, scraping blocked).

## League Context Verification

League: Fantasy Bahamas, 12-team PPR auction, $250 budget (Sleeper draft settings),
2 FLEX slots, 40+ bonuses at 1.0, rec=1.0.
Verified against docs/references/league.md: correct.

## Week 1 Projection Assessment

### What the model does well

1. **Weighted recency + prior-season blend** handles early season correctly.
   Week 1 (no same-season history) uses full prior-season REG average, which is
   the right call for projections when no 2026 data exists yet.

2. **Out-zeroing** (refresh.py:663) correctly handles confirmed Outs. Tested with
   the Darnold example (projected 163 yds while Out, fixed to 0).

3. **2-FLEX scoring** reflected in FLEX_SCARCITY_MULTIPLIER=1.05 and POS_REPL_COUNTS
   (RB:28, WR:32 vs standard 24). Appropriate for this league format.

4. **Bonus scoring** (40+ yard plays at 1.0) included in DEFAULT_SCORING and stat maps.

### Areas a sharp manager would question

1. **QB projection intervals too narrow at the top** (S1 finding): QB coverage is 33%
   at n=3 in 2026 live data. Elite QBs (Allen, Hurts, Lamar) have fat tails.
   A sharp manager seeing Josh Allen projected 22.5 +/- 7.0 would note his actual
   range is more like 12-45. The 1.45x QB factor helps but doesn't fully capture
   the bimodal distribution (rushing QBs have feast-or-famine games).

2. **No depth chart awareness in projections**: stat_projector uses prior-season
   averages without knowing if the player is the starter. The depth chart data IS
   fetched (refresh.py:723-727, gsis_depth_rank()) but NOT used in projections.
   A backup RB thrust into a starting role after an injury would be projected at
   his backup-level prior average, not at starter usage.
   Counterpoint: snap-share scaling was tested and REJECTED (stat_projector.py:44-56,
   paired-t overall t=1.66, p~0.10). The mechanism is right but the signal isn't
   strong enough statistically. Display-level demotion is the current mitigation.

3. **Bye week handling**: Week 1 has no byes, but the model defaults to
   implied_total=21.0 for missing game context (stat_projector.py:715).
   This is conservative and correct.

4. **Weather placeholder**: All weather badges show placeholder (40.0/-74.0 coords).
   A sharp manager would ignore wind badges until real stadium coords land.

## Hashtag Football Assessment

Per hashtag-research.md: all automated scraping blocked (robots.txt disallows AI crawlers).
Manual cross-check only.

| Tool | Feature | nflverse Overlap | Value Rating | Go/No-Go |
|------|---------|-----------------|--------------|----------|
| Target Shares | target share % | Full (opportunity feed) | Low (already have) | No-Go (scraping blocked + already have) |
| Snap Shares | snap count % | Full (weekly stats) | Low | No-Go |
| Reception Rate | catch rate | Full (derivable) | Low | No-Go |
| Carries | rush attempts | Full | Low | No-Go |
| RB Workload | combined touches | Full (derivable) | Low | No-Go |
| Slot vs Perimeter | route tree split | None | High | No-Go (scraping blocked) |
| QB Advanced Efficiency | EPA/CPOE | Partial (PBP) | Medium | No-Go (scraping blocked, PBP available) |
| RB Elusiveness | broken tackle rate | None | Medium | No-Go (scraping blocked) |
| CB Coverage | matchup data | None | High | No-Go (scraping blocked) |
| Consistency | boom/bust rate | Derivable from history | Medium | Compute internally |
| PPR Rankings | ECR equivalent | Full (nflverse ECR) | Low | No-Go |
| Projections | point projections | Comparison baseline | Medium | Manual cross-check only |
| Injury Database | injury timeline | Partial (Sleeper) | Medium | No-Go (scraping blocked) |

**High-value features unavailable for automation:** Slot/perimeter splits and CB coverage
are the two features nflverse lacks that would add real signal. Both are scraping-blocked.
Explore nflverse PBP for route data derivation as an alternative.

**Actionable:** Compute boom/bust consistency score from stored player_stats history
(no external data needed). This feeds interval width estimation.
