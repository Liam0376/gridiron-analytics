# Data Notice — Third-Party Data Is Not Ours to Redistribute

MIT (`LICENSE`) covers **code only**. It does not cover third-party fantasy
data fetched at refresh time.

## Provenance

- **FantasyPros** (draft rankings / ADP / projections CSVs, e.g.
  `FantasyPros_*.csv`): proprietary. Terms at
  https://www.fantasypros.com/terms/ — do not republish or commit these
  files. Each user fetches their own copy at refresh time and keeps it
  local (gitignored). Files previously tracked were untracked via
  `git rm --cached` (history left alone); on-disk copies are yours to
  delete or keep locally.
- **Sleeper API** (`https://api.sleeper.app`): free for personal use per
  https://docs.sleeper.com/ — fetched live at refresh time, never vendored.
- **nflverse / nflreadpy** (play-by-play, schedules, rosters): open data per
  https://nflverse.nflverse.com/ — fetched at refresh time into local cache
  (`data/nfl_cache/`, gitignored).
- **Open-Meteo** (weather): free non-commercial API per
  https://open-meteo.com/en/terms — fetched live, never stored for
  redistribution.

## Rules for contributors and users

1. **Fetch at refresh time, don't commit.** No third-party CSV/JSONL/DB
   snapshots in git. `FantasyPros_*.csv`, `data/fantasy.db*` (including
   `data/fantasy.db.bak-*`), `data/nfl_cache/`, `data/ml/*.jsonl`, and
   `logs/` are gitignored.
2. **No redistribution.** Do not attach fetched data to issues/PRs, and do
   not publish forks containing it.
3. **Local-only, $0, NFL-only, no betting.** All fetches are outbound-only
   to the free APIs above; services bind `127.0.0.1`, single private league
   via `SLEEPER_LEAGUE_ID` (see `.env.example`).

Questions about what may be shared: share code and `docs/`, never `data/`
contents or third-party CSVs.
