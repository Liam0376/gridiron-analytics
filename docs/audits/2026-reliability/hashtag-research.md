# Hashtag Football Tool Research

Domain: hashtagfootball.com (sister site to hashtagbasketball.com)

## Scraping Verdict: NO-GO

robots.txt (Cloudflare-managed) blocks all AI crawlers:
- `ClaudeBot: Disallow: /`
- `GPTBot: Disallow: /`
- `Google-Extended: Disallow: /`
- `Content-Signal: ai-train=no, use=reference`

Data is client-side rendered (JS tables, "Loading..." placeholder). No public API. Automated scraping would violate both robots.txt and the spirit of the $0 constraint (premium league tools exist at $2.50/mo).

**Decision: Use Hashtag Football for manual cross-checks only. No automated ingest.**

## Tool Catalog

### Usage & Role Tools

| Tool | Data Provided | nflverse Overlap | Value | Go/No-Go |
|------|--------------|-----------------|-------|----------|
| NFL Target Shares | Targets, target share, RZ targets, air yards per player | **Full overlap**: nflverse `load_player_stats` has targets, `load_ngs_receiving` has target share, opportunity feed has rec_attempt/team share | Low | No-Go (nflverse covers it) |
| NFL Snap Shares | Snaps, snap share per player | **Full overlap**: nflverse `load_player_stats` has snap counts | Low | No-Go |
| NFL Reception Rate | Receptions, reception rate | **Full overlap**: trivially derived from nflverse targets+receptions | Low | No-Go |
| NFL Carries | Carries, carry share | **Full overlap**: nflverse has carries, opportunity feed has rush_attempt/team | Low | No-Go |
| NFL RB Workload | Combined RB touches, snap share, opportunity share | **Full overlap**: derivable from nflverse opportunity + snap data | Low | No-Go |
| NFL Slot vs Perimeter | Slot rate, slot targets, perimeter targets | **Partial**: nflverse NGS has some route data but slot/perimeter split less accessible | Medium | No-Go (robots.txt) |

### Efficiency & Matchup Tools

| Tool | Data Provided | nflverse Overlap | Value | Go/No-Go |
|------|--------------|-----------------|-------|----------|
| NFL QB Advanced Efficiency | Completion %, YPA, sack rate, pressure rate | **Full overlap**: nflverse `load_player_stats` has all QB efficiency | Low | No-Go |
| NFL RB Elusiveness | Yards after contact, broken tackles | **Partial**: nflverse PBP has yards after contact; elusiveness rating is derived | Medium | No-Go (robots.txt) |
| NFL Cornerback Coverage | CB coverage stats, targets allowed | **Unique**: nflverse does not have CB-level coverage matchup data | High | No-Go (robots.txt) |

### Variance & Rankings Tools

| Tool | Data Provided | nflverse Overlap | Value | Go/No-Go |
|------|--------------|-----------------|-------|----------|
| Fantasy Football Consistency | Boom/bust rates, scoring range (FROM/TO), average | **Unique presentation**: boom/bust thresholds are derived; we can compute from our own data | Medium | No-Go (robots.txt, derivable) |
| PPR Rankings / Positional Rankings | Expert consensus rankings | **Overlap**: nflverse free ECR weekly covers this | Low | No-Go |
| Fantasy Football Projections | Per-player point projections | **Overlap**: Sleeper projections + our model already | Low | No-Go |

### Decision Tools

| Tool | Data Provided | nflverse Overlap | Value | Go/No-Go |
|------|--------------|-----------------|-------|----------|
| Who Should I Start? | Start/sit recommendation engine | N/A (decision layer, not data) | Low | No-Go |
| Trade Analyzer | Trade value calculator | N/A (decision layer) | Low | No-Go |
| Who Should I Draft? | Draft recommendation | N/A | Low | No-Go |
| NFL Injury Database | Injury history, status | **Partial overlap**: Sleeper injury_status + nflverse load_injuries() | Medium | No-Go (robots.txt) |
| Box Scores | Game box scores | **Full overlap**: nflverse PBP + player stats | Low | No-Go |

## Summary

- **0 tools rated Go**: robots.txt universally blocks automated access
- **2 tools with unique data** (CB Coverage, Slot/Perimeter split): potentially High value as model features but not accessible for automated ingest
- **Most tools fully overlap with nflverse**: target share, snap share, carries, QB efficiency, reception rate, workload all derivable from existing nflverse feeds already in the pipeline
- **Consistency (boom/bust)**: unique presentation but the underlying concept (scoring variance) is derivable from our own historical player_stats. We should compute our own boom/bust rates from stored data rather than sourcing externally.

## Recommendation for Pipeline Agent

No automated Hashtag Football ingest. Instead:
1. **CB Coverage matchup**: If this feature is wanted, explore Pro Football Reference or nflverse PBP-derived coverage stats (free, scrapeable)
2. **Boom/bust consistency**: Compute internally from player_stats history (stddev, percentile thresholds)
3. **Slot rate**: Check if nflverse NGS or route data covers this; if not, defer
4. **Manual cross-check**: Use Hashtag Football rankings/projections as a human sanity check against our model output during the Expert audit, not as automated ingest
