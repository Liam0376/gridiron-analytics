# Free Data Source Research — August 2026

Research phase per project process. All findings verified via live web search (not
training-data memory) — sports-data APIs change free tiers often.

## Summary table

| Category | Winner | Cost | Auth | Notes |
|---|---|---|---|---|
| Play-by-play / weekly stats / snaps / NGS | **nflreadpy** | Free | None | Successor to archived `nfl_data_py` |
| League scoring/rosters/matchups/waivers | **Sleeper API** | Free | None | Official docs, stable |
| Injury status (daily) | **Sleeper API** (`injury_status` field) | Free | None | Resets Wed mornings, game-week scoped |
| Injury status (historical/backup) | **nflreadpy** `load_injuries()` | Free | None | Weekly cadence, CC-BY-SA attribution to FTN |
| News/roster moves/depth charts | **ESPN hidden API** (fallback only) | Free | None | Unofficial, can break without notice |
| Weather (forecast, outdoor games) | **Open-Meteo** | Free | None | 16-day forecast, ~10k calls/day |

## 1. nflverse / nfl_data_py → nflreadpy

**`nfl_data_py` is archived/dead** (last release ~March 2023). Its Python successor
is **`nflreadpy`**, actively maintained (commits as recent as Aug 2026), modeled on
R's `nflreadr`.

- Covers: play-by-play, weekly stats, snap counts, rosters (back to 1920), schedules,
  Next Gen Stats (target share, air yards, aDOT, WOPR). Red-zone touches NOT a
  first-class field — derive from play-by-play if needed.
- 100% free, no auth, no rate limit — direct parquet/csv file downloads from GitHub
  releases (`nflverse-data` repo), not a rate-limited API.
- **Gotcha: returns Polars DataFrames, not pandas.** `.to_pandas()` to convert.
  Package itself is tagged "experimental" — pin a version, don't auto-upgrade blind.
- **Gotcha: `.qs` file format dropped Jan 2026** — parquet/rds/csv only now.
- Freshness: PBP available ~15 min post-game (raw), cleaned by next morning, fully
  corrected by Thursday (NFL stat correction window).
- Install: `pip install nflreadpy`

**Decision: use `nflreadpy`, not `nfl_data_py`.** The original prompt referenced
`nfl_data_py` — that package is dead; adopting the maintained successor.

## 2. Sleeper API

Confirmed free, public, read-only, no API key. Official docs at docs.sleeper.com.

- Endpoints: league settings (`scoring_settings` — flat key/value map, e.g.
  `pass_td`, `rec`, `rec_yd`), rosters, users, matchups, transactions, full player
  DB (`/v1/players/nfl`, ~5MB — fetch at most once/day), trending adds/drops.
- Rate limit: keep under ~1000 calls/min (some sources cite ~90/min — be
  conservative, cache aggressively, don't hammer `/players/nfl`).
- Injury field: `injury_status` on player objects (Questionable/Doubtful/Out/null),
  updates daily, resets Wednesdays at start of new NFL week.
- **This is the primary source for league-exact scoring** — pull `scoring_settings`
  programmatically, verify against Fantasy Bahamas' actual settings at season start
  and don't hardcode.

## 3. ESPN hidden/undocumented API

Unofficial, no formal docs, but widely used (`cwendt94/espn-api` Python wrapper
actively maintained). Free, no auth for public endpoints.

- Base URL for fantasy v3 **moved April 2024** to `lm-api-reads.fantasy.espn.com` —
  a real example of "can change without notice."
- Covers scores/schedules/box scores/rosters. Does **not** have a dedicated
  injury/news endpoint — that data lives on the espn.com website, not the API.
- **Risk accepted explicitly**: no SLA, no changelog, community-tracked breakage.
  Use only as a fallback / cross-check source, never as the sole path for anything
  the decision layer depends on.

## 4. Injury reports (hardest category, per brief)

No single clean daily-refreshed free source with practice-participation detail.
Landed on a two-tier approach:

- **Primary (daily, in-season): Sleeper `injury_status`.** Free, current, simple
  field, already being pulled for league data anyway — no extra integration cost.
- **Secondary (historical/backfill): `nflreadpy.load_injuries()`.** Weekly cadence,
  official practice-participation detail, good for backtesting/shadow-mode
  evaluation, not for daily "is he playing Sunday" checks.
- **Rejected**: commercial free tiers (SportsDataIO, API-Sports) exclude injury
  data from their free quota — confirmed during research, not assumed. Scraping
  nfl.com directly rejected — ToS violation, and Sleeper already covers the need
  for free with no legal exposure.

## 5. Weather

**Open-Meteo** — free, no key, no card, ~10k calls/day, 16-day forecast (covers a
Wed/Thu lookahead to Sunday games), multiple NWP models. Beats OpenWeatherMap
(5-day cap on free tier, key required) and WeatherAPI.com (3-day cap on free tier).
NWS/api.weather.gov rejected — undocumented rate limits, reported reliability
issues under load, US-only (fine for NFL, but no upside over Open-Meteo).

## Net effect on architecture

- No paid tier anywhere in the stack — constraint satisfied.
- Two free, unauthenticated, actively-maintained sources (nflreadpy, Sleeper) cover
  ~90% of data needs. ESPN is fallback-only, treated as unreliable by design.
- Biggest real risk isn't cost, it's **breakage without notice** on the unofficial
  ESPN path and the "experimental" tag on nflreadpy — spec should isolate both
  behind an adapter layer so a breaking change is a one-file fix, not a rewrite.
