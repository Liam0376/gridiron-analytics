# Gridiron Analytics

High-performance fantasy football analytics engine and local command center.

Gridiron Analytics combines statistical projection models, conformal uncertainty intervals, league-calibrated auction pricing, and a fast local UI for draft and in-season management.

## Features

- **Statistical Projections:** Weighted-recent averages, position-level TD regression, volume trends, Vegas totals, and weather penalties.
- **Calibrated Uncertainty:** Conformal prediction intervals (80% confidence bounds) for every player recommendation.
- **Auction Draft Guide:** Custom Value Over Replacement (VOR) pricing calibrated specifically for your roster and budget settings.
- **Matchup & Weather Analysis:** Integrated wind speed and temperature impact models.
- **Local Privacy:** Runs entirely on `127.0.0.1`. Zero external tracking, zero cloud dependencies.

## Architecture

- **Engine (`src/ffanalytics`):** Python backend powered by FastAPI, SQLite WAL storage, and `nflreadpy` data pipelines.
- **Hub (`hub/`):** Zero-dependency Vite and vanilla JavaScript web application.
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
   ```

2. Start the local engine and UI:
   ```bash
   bash hub/start.sh
   ```

   This launches the FastAPI model backend (`:8000`), the read-only database proxy (`:8002`), and the web interface (`:8001`), then opens `http://127.0.0.1:8001` in your browser.

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

MIT
