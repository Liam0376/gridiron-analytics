# Gridiron Analytics

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Fantasy football analytics engine + local command center.

Gridiron Analytics combines statistical projection models, conformal uncertainty intervals, league-calibrated auction pricing, and a fast local UI for draft and in-season management.

## Features

- **Statistical Projections:** weighted-recent averages, position-level TD regression, volume trends, Vegas totals, weather penalties.
- **Calibrated Uncertainty:** conformal prediction intervals (80% confidence bounds) per player.
- **Auction Draft Guide:** custom Value Over Replacement (VOR) pricing calibrated for your roster and budget.
- **Matchup & Weather:** integrated wind speed and temperature impact models.
- **Local Privacy:** runs entirely on `127.0.0.1`.

## Architecture

- **Engine (`src/ffanalytics`):** FastAPI + SQLite (WAL) + `nflreadpy` pipelines.
- **Hub (`hub/`):** Vite + vanilla JS.
- **Proxy (`hub/server.py`):** Read-only SQLite proxy preventing state mutation during UI navigation.

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+

### Setup & Launch

1. Install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   # ML extras (backtests only — production uses the statistical projector):
   # pip install -e .[ml]
   ```

2. Configure your league (each user runs their own single league —
   multi-league is an explicit non-goal for OSS v1):
   ```bash
   cp .env.example .env && chmod 600 .env
   # Edit .env and set SLEEPER_LEAGUE_ID to your league ID.
   ```

3. Start the local engine and UI:
   ```bash
   bash hub/start.sh
   ```

   Launches FastAPI on :8000, read-only DB proxy on :8002, Vite UI on :8001; opens http://127.0.0.1:8001.
   All binds are `127.0.0.1` only. See `docs/RUNBOOK.md` for env details,
   health-vs-ready, scheduled refresh, and backup/restore.

## Backup / Restore

```bash
sqlite3 data/fantasy.db ".backup 'data/fantasy.db.bak-$(date +%F)'"
sqlite3 data/fantasy.db "VACUUM;"
```

Full procedure in `docs/RUNBOOK.md`.

## Data files (Git LFS)

Third-party data is never committed — see [DATA_NOTICE.md](DATA_NOTICE.md)
(provenance, no-redistribution, fetch-at-refresh-time; MIT covers code only).

`data/ml/*.jsonl` and `data/nfl_cache/` are large and LFS-tracked (see
`.gitattributes`). Contributors: use Git LFS for anything in those paths —
do not commit large files without it, and do not rewrite history to slim the
repo (leave history alone).

## Contributing & Conduct

See [LICENSE](LICENSE), [.env.example](.env.example),
[DATA_NOTICE.md](DATA_NOTICE.md), [docs/RUNBOOK.md](docs/RUNBOOK.md), and
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). Be kind and keep it local-only —
no tunnels, no paid services, no betting logic.

## Platform note

`FantasyHub.app/` is a macOS-only binary wrapper (double-click launcher).
On other platforms use `bash hub/start.sh` directly.

## Testing & Verification

Run the test suite:
```bash
SLEEPER_LEAGUE_ID=test .venv/bin/pytest -q
```

Verify model-hub architecture isolation:
```bash
bash hub/verify-isolation.sh
```

## License

MIT — see [LICENSE](LICENSE).
