# Fantasy Football Analytics Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only FastAPI service + SQLite store that produces
calibrated, shadow-logged start/sit, waiver, and trade recommendations for one
Sleeper fantasy football league, using free data sources only.

**Architecture:** launchd-scheduled refresh job pulls from three isolated
adapters (nflreadpy, Sleeper API, Open-Meteo) into SQLite; a rating/projection
engine (Glicko-2 team + positional-matchup strength, conformal-calibrated
projections) computes weekly numbers; FastAPI serves them locally from an
in-memory cache; every recommendation is shadow-logged for later backtesting.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, SQLite (stdlib `sqlite3`,
WAL mode), `nflreadpy` (Polars), `requests` (Sleeper + Open-Meteo — both plain
REST/JSON, no SDK needed), `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-26-fantasy-football-analytics-design.md`

## Global Constraints

- $0 cost: no paid dependency, no paid hosting, no service requiring a card.
- No network calls in unit tests — adapters are tested against fixture data /
  mocked HTTP, never live APIs (live calls are integration-tested manually,
  documented per-task where relevant).
- Every feature used by the projection engine must have an entry in
  `config.py`'s `FEATURES` dict with a `why` — no feature added silently.
- SQLite is the only datastore. One file: `data/fantasy.db`.
- Polars (`nflreadpy`'s return type) never leaks past `adapters/nflverse.py` —
  every adapter returns plain dicts/lists of dicts at its boundary.

---

### Task 1: Project scaffold + config module

**Files:**
- Create: `pyproject.toml`
- Create: `src/ffanalytics/__init__.py`
- Create: `src/ffanalytics/config.py`
- Create: `tests/test_config.py`
- Create: `.gitignore`
- Create: `requirements.txt` (pinned versions — reference repo pattern)

**Interfaces:**
- Produces: `config.FEATURES: dict[str, dict]` (keys: `status` ∈
  `{"included", "rejected"}`, `why: str`), `config.DB_PATH: pathlib.Path`,
  `config.LEAGUE_ID: str` (loaded from env var `SLEEPER_LEAGUE_ID`, no
  default — fail loudly if unset), `config.get_feature_status(name: str) -> str`.

- [ ] **Step 1: Write `pyproject.toml` and `requirements.txt`**

```toml
[project]
name = "ffanalytics"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "nflreadpy>=0.1",
    "requests>=2.32",
    "pydantic>=2.9",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

```
fastapi>=0.115
uvicorn>=0.30
nflreadpy>=0.1
requests>=2.32
pydantic>=2.9
pytest>=8.3
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
data/*.db
data/*.db-wal
data/*.db-shm
.pytest_cache/
```

- [ ] **Step 3: Write the failing test for config**

```python
# tests/test_config.py
import os
import pytest

def test_league_id_missing_raises(monkeypatch):
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    import importlib
    import ffanalytics.config as config_module
    with pytest.raises(RuntimeError, match="SLEEPER_LEAGUE_ID"):
        importlib.reload(config_module)

def test_get_feature_status_known_and_unknown(monkeypatch):
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "123")
    import importlib
    import ffanalytics.config as config_module
    importlib.reload(config_module)
    assert config_module.get_feature_status("target_share") == "included"
    with pytest.raises(KeyError):
        config_module.get_feature_status("not_a_real_feature")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffanalytics'`

- [ ] **Step 3: Write `src/ffanalytics/__init__.py`** (empty file)

- [ ] **Step 4: Write `src/ffanalytics/config.py`**

```python
import os
from pathlib import Path

LEAGUE_ID = os.environ.get("SLEEPER_LEAGUE_ID")
if not LEAGUE_ID:
    raise RuntimeError(
        "SLEEPER_LEAGUE_ID env var must be set — this project never "
        "hardcodes league settings, see CLAUDE.md"
    )

DB_PATH = Path(os.environ.get("FFANALYTICS_DB_PATH", "data/fantasy.db"))

# Every feature the projection engine uses is declared here with why it's
# in, or (once tested) why it was rejected. See docs/superpowers/specs/
# 2026-08-26-fantasy-football-analytics-design.md#feature-selection-discipline
FEATURES = {
    "target_share": {
        "status": "included",
        "why": "strongest single predictor of weekly receiving points; "
               "to be confirmed against real backtests once shadow data "
               "accumulates",
    },
    "snap_pct": {
        "status": "included",
        "why": "proxy for role/opportunity independent of target share; "
               "catches role changes before target share reflects them",
    },
    "opponent_positional_rating": {
        "status": "included",
        "why": "core defense-adjustment signal — see rating engine in "
               "the design spec",
    },
}

def get_feature_status(name: str) -> str:
    return FEATURES[name]["status"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt .gitignore src/ffanalytics/__init__.py src/ffanalytics/config.py tests/test_config.py
git commit -m "feat: project scaffold + config module with feature discipline"
```

---

### Task 2: SQLite schema + connection helper

**Files:**
- Create: `src/ffanalytics/db.py`
- Create: `src/ffanalytics/schema.sql`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `config.DB_PATH`
- Produces: `db.get_connection(path: Path | None = None) -> sqlite3.Connection`
  (WAL mode enabled, `row_factory = sqlite3.Row`), `db.init_schema(conn) -> None`

- [ ] **Step 1: Write `src/ffanalytics/schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS team_ratings (
    team TEXT NOT NULL,
    position_group TEXT NOT NULL,  -- 'overall', 'vs_rb', 'vs_wr_slot', 'vs_te', etc.
    rating REAL NOT NULL,
    rating_deviation REAL NOT NULL,
    last_updated_week INTEGER NOT NULL,
    season INTEGER NOT NULL,
    PRIMARY KEY (team, position_group, season)
);

CREATE TABLE IF NOT EXISTS refresh_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- 'nflreadpy', 'sleeper', 'open-meteo'
    ran_at TEXT NOT NULL,           -- ISO8601, passed in by caller (no Date.now in workflows, but fine at runtime)
    success INTEGER NOT NULL,       -- 0/1
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS shadow_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,             -- 'start_sit', 'waiver', 'trade'
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    player_id TEXT,
    recommendation TEXT NOT NULL,   -- JSON blob: inputs + output
    logged_at TEXT NOT NULL,
    actual_outcome TEXT             -- filled in later by refresh job; JSON or NULL
);
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_db.py
import sqlite3
import tempfile
from pathlib import Path

def test_init_schema_creates_tables():
    from ffanalytics import db
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.db"
        conn = db.get_connection(path)
        db.init_schema(conn)
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"team_ratings", "refresh_log", "shadow_recommendations"} <= tables
        conn.close()

def test_get_connection_uses_wal_mode():
    from ffanalytics import db
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.db"
        conn = db.get_connection(path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        conn.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'ffanalytics.db' has no attribute 'get_connection'`

- [ ] **Step 4: Write `src/ffanalytics/db.py`**

```python
import sqlite3
from pathlib import Path

from ffanalytics import config

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

def get_connection(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/ffanalytics/db.py src/ffanalytics/schema.sql tests/test_db.py
git commit -m "feat: SQLite schema + WAL connection helper"
```

---

### Task 3: Sleeper adapter

**Files:**
- Create: `src/ffanalytics/adapters/__init__.py`
- Create: `src/ffanalytics/adapters/sleeper.py`
- Create: `tests/fixtures/sleeper_league.json`
- Create: `tests/fixtures/sleeper_rosters.json`
- Test: `tests/adapters/test_sleeper.py`

**Interfaces:**
- Consumes: `config.LEAGUE_ID`
- Produces: `sleeper.get_league_settings(league_id: str, session=None) -> dict`
  (returns `{"scoring_settings": {...}, "roster_positions": [...]}`),
  `sleeper.get_rosters(league_id: str, session=None) -> list[dict]`,
  `sleeper.get_injury_statuses(session=None) -> dict[str, str | None]` (player_id → status)

- [ ] **Step 1: Write fixture files**

```json
// tests/fixtures/sleeper_league.json
{
  "league_id": "123",
  "scoring_settings": {"rec": 1.0, "rec_yd": 0.1, "rush_yd": 0.1, "pass_yd": 0.04, "pass_td": 5, "rush_td": 6, "rec_td": 6, "pass_int": -1},
  "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF", "BN", "BN", "BN", "BN", "IR", "IR"]
}
```

```json
// tests/fixtures/sleeper_rosters.json
[
  {"roster_id": 1, "owner_id": "u1", "players": ["4046", "5849"]}
]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/adapters/test_sleeper.py
import json
from pathlib import Path
from unittest.mock import Mock

FIXTURES = Path(__file__).parent.parent / "fixtures"

def _mock_session(payload):
    session = Mock()
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    session.get.return_value = response
    return session

def test_get_league_settings_returns_scoring_and_roster():
    from ffanalytics.adapters import sleeper
    payload = json.loads((FIXTURES / "sleeper_league.json").read_text())
    session = _mock_session(payload)
    result = sleeper.get_league_settings("123", session=session)
    assert result["scoring_settings"]["rec"] == 1.0
    assert "FLEX" in result["roster_positions"]
    session.get.assert_called_once_with(
        "https://api.sleeper.app/v1/league/123", timeout=10
    )

def test_get_rosters_returns_list():
    from ffanalytics.adapters import sleeper
    payload = json.loads((FIXTURES / "sleeper_rosters.json").read_text())
    session = _mock_session(payload)
    result = sleeper.get_rosters("123", session=session)
    assert result[0]["roster_id"] == 1

def test_get_injury_statuses_filters_to_nonnull():
    from ffanalytics.adapters import sleeper
    payload = {
        "4046": {"player_id": "4046", "injury_status": "Questionable"},
        "5849": {"player_id": "5849", "injury_status": None},
    }
    session = _mock_session(payload)
    result = sleeper.get_injury_statuses(session=session)
    assert result == {"4046": "Questionable", "5849": None}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/adapters/test_sleeper.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffanalytics.adapters'`

- [ ] **Step 4: Write `src/ffanalytics/adapters/__init__.py`** (empty file)

- [ ] **Step 5: Write `src/ffanalytics/adapters/sleeper.py`**

```python
import requests

BASE_URL = "https://api.sleeper.app/v1"

def _session_or_default(session):
    return session or requests

def get_league_settings(league_id: str, session=None) -> dict:
    http = _session_or_default(session)
    resp = http.get(f"{BASE_URL}/league/{league_id}", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return {
        "scoring_settings": data["scoring_settings"],
        "roster_positions": data["roster_positions"],
    }

def get_rosters(league_id: str, session=None) -> list[dict]:
    http = _session_or_default(session)
    resp = http.get(f"{BASE_URL}/league/{league_id}/rosters", timeout=10)
    resp.raise_for_status()
    return resp.json()

def get_injury_statuses(session=None) -> dict[str, str | None]:
    """Fetch full player DB and extract injury_status. Sleeper docs say
    fetch this at most once/day — caller (refresh job) is responsible for
    that cadence, this function just does one call."""
    http = _session_or_default(session)
    resp = http.get(f"{BASE_URL}/players/nfl", timeout=30)
    resp.raise_for_status()
    players = resp.json()
    return {pid: p.get("injury_status") for pid, p in players.items()}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/adapters/test_sleeper.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add src/ffanalytics/adapters/__init__.py src/ffanalytics/adapters/sleeper.py tests/adapters/test_sleeper.py tests/fixtures/sleeper_league.json tests/fixtures/sleeper_rosters.json
git commit -m "feat: Sleeper API adapter (league settings, rosters, injuries)"
```

---

### Task 4: nflreadpy adapter (Polars boundary)

**Files:**
- Create: `src/ffanalytics/adapters/nflverse.py`
- Test: `tests/adapters/test_nflverse.py`

**Interfaces:**
- Consumes: `nflreadpy.load_player_stats`, `nflreadpy.load_injuries` (mocked in
  tests — never call the real network in unit tests)
- Produces: `nflverse.get_weekly_player_stats(season: int, session_module=None) -> list[dict]`
  (plain dicts, no Polars object survives this boundary),
  `nflverse.get_injury_history(season: int, session_module=None) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_nflverse.py
from unittest.mock import Mock

class _FakePolarsFrame:
    """Minimal stand-in for a polars.DataFrame — only needs to_dicts()."""
    def __init__(self, rows):
        self._rows = rows
    def to_dicts(self):
        return self._rows

def test_get_weekly_player_stats_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_player_stats.return_value = _FakePolarsFrame(
        [{"player_id": "4046", "target_share": 0.28}]
    )
    result = nflverse.get_weekly_player_stats(2026, nfl_module=fake_nfl)
    assert result == [{"player_id": "4046", "target_share": 0.28}]
    assert isinstance(result, list)
    assert isinstance(result[0], dict)
    fake_nfl.load_player_stats.assert_called_once_with(seasons=[2026])

def test_get_injury_history_converts_to_plain_dicts():
    from ffanalytics.adapters import nflverse
    fake_nfl = Mock()
    fake_nfl.load_injuries.return_value = _FakePolarsFrame(
        [{"player_id": "4046", "report_status": "Questionable"}]
    )
    result = nflverse.get_injury_history(2026, nfl_module=fake_nfl)
    assert result == [{"player_id": "4046", "report_status": "Questionable"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_nflverse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffanalytics.adapters.nflverse'`

- [ ] **Step 3: Write `src/ffanalytics/adapters/nflverse.py`**

```python
"""Wraps nflreadpy. This is the ONLY file in the project allowed to import
nflreadpy / touch a Polars object — every function here returns plain
list[dict] so Polars never leaks into the rest of the codebase (see
Global Constraints in the plan)."""

def _nfl_module(nfl_module):
    if nfl_module is not None:
        return nfl_module
    import nflreadpy
    return nflreadpy

def get_weekly_player_stats(season: int, nfl_module=None) -> list[dict]:
    nfl = _nfl_module(nfl_module)
    frame = nfl.load_player_stats(seasons=[season])
    return frame.to_dicts()

def get_injury_history(season: int, nfl_module=None) -> list[dict]:
    nfl = _nfl_module(nfl_module)
    frame = nfl.load_injuries(seasons=[season])
    return frame.to_dicts()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_nflverse.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ffanalytics/adapters/nflverse.py tests/adapters/test_nflverse.py
git commit -m "feat: nflreadpy adapter, isolates Polars behind plain-dict boundary"
```

---

### Task 5: Open-Meteo weather adapter

**Files:**
- Create: `src/ffanalytics/adapters/weather.py`
- Test: `tests/adapters/test_weather.py`

**Interfaces:**
- Produces: `weather.get_forecast(lat: float, lon: float, game_time_iso: str, session=None) -> dict | None`
  (returns `{"temp_f": float, "wind_mph": float, "precip_prob": float}` for
  the forecast hour closest to `game_time_iso`, or `None` if the API call
  fails — soft-fail per spec, never raises)

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_weather.py
from unittest.mock import Mock

def _mock_session(payload=None, raises=False):
    session = Mock()
    if raises:
        session.get.side_effect = ConnectionError("boom")
        return session
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    session.get.return_value = response
    return session

def test_get_forecast_picks_closest_hour():
    from ffanalytics.adapters import weather
    payload = {
        "hourly": {
            "time": ["2026-09-14T12:00", "2026-09-14T13:00", "2026-09-14T14:00"],
            "temperature_2m": [70.0, 68.0, 66.0],
            "wind_speed_10m": [5.0, 8.0, 10.0],
            "precipitation_probability": [10, 20, 30],
        }
    }
    session = _mock_session(payload)
    result = weather.get_forecast(40.5, -74.0, "2026-09-14T13:05:00", session=session)
    assert result == {"temp_f": 68.0, "wind_mph": 8.0, "precip_prob": 20}

def test_get_forecast_returns_none_on_failure():
    from ffanalytics.adapters import weather
    session = _mock_session(raises=True)
    result = weather.get_forecast(40.5, -74.0, "2026-09-14T13:05:00", session=session)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_weather.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/ffanalytics/adapters/weather.py`**

```python
"""Open-Meteo adapter. Soft-fail by design (spec: weather is a soft-fail
feature, not a hard dependency) — returns None on any error instead of
raising, so a refresh job never blocks on this one adapter."""

from datetime import datetime

import requests

BASE_URL = "https://api.open-meteo.com/v1/forecast"

def get_forecast(lat: float, lon: float, game_time_iso: str, session=None) -> dict | None:
    http = session or requests
    try:
        resp = http.get(
            BASE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,wind_speed_10m,precipitation_probability",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "forecast_days": 16,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        times = data["hourly"]["time"]
        target = datetime.fromisoformat(game_time_iso)
        closest_idx = min(
            range(len(times)),
            key=lambda i: abs((datetime.fromisoformat(times[i]) - target).total_seconds()),
        )
        return {
            "temp_f": data["hourly"]["temperature_2m"][closest_idx],
            "wind_mph": data["hourly"]["wind_speed_10m"][closest_idx],
            "precip_prob": data["hourly"]["precipitation_probability"][closest_idx],
        }
    except Exception:
        return None
```

Note: `session.get` in the test is a `Mock` that doesn't take `params=` into
account for matching — the test only checks the return value, which is fine
since the mock ignores kwargs and returns the fixed payload regardless.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/test_weather.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ffanalytics/adapters/weather.py tests/adapters/test_weather.py
git commit -m "feat: Open-Meteo weather adapter, soft-fails to None"
```

---

### Task 6: Glicko-2 rating engine (team + positional matchup)

**Files:**
- Create: `src/ffanalytics/rating.py`
- Test: `tests/test_rating.py`

**Interfaces:**
- Produces: `rating.Rating` (dataclass: `value: float`, `deviation: float`),
  `rating.DEFAULT_RATING = Rating(1500.0, 350.0)`,
  `rating.update(current: Rating, opponent: Rating, score: float, k_factor: float) -> Rating`
  (`score` is 1.0/0.5/0.0 win/tie/loss, standard Glicko-ish update — value
  moves toward the expected-vs-actual score, deviation shrinks with each
  game and grows over `weeks_since_last_game` via `decay_for_inactivity`),
  `rating.decay_for_inactivity(current: Rating, weeks_since_last_game: int) -> Rating`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rating.py
from ffanalytics.rating import Rating, DEFAULT_RATING, update, decay_for_inactivity

def test_default_rating_values():
    assert DEFAULT_RATING.value == 1500.0
    assert DEFAULT_RATING.deviation == 350.0

def test_update_winner_rating_increases():
    r = update(DEFAULT_RATING, DEFAULT_RATING, score=1.0, k_factor=32.0)
    assert r.value > DEFAULT_RATING.value

def test_update_loser_rating_decreases():
    r = update(DEFAULT_RATING, DEFAULT_RATING, score=0.0, k_factor=32.0)
    assert r.value < DEFAULT_RATING.value

def test_update_shrinks_deviation():
    r = update(DEFAULT_RATING, DEFAULT_RATING, score=1.0, k_factor=32.0)
    assert r.deviation < DEFAULT_RATING.deviation

def test_decay_for_inactivity_grows_deviation_with_weeks():
    settled = update(DEFAULT_RATING, DEFAULT_RATING, score=1.0, k_factor=32.0)
    decayed_1wk = decay_for_inactivity(settled, weeks_since_last_game=1)
    decayed_4wk = decay_for_inactivity(settled, weeks_since_last_game=4)
    assert decayed_1wk.deviation > settled.deviation
    assert decayed_4wk.deviation > decayed_1wk.deviation

def test_decay_never_exceeds_default_deviation():
    settled = update(DEFAULT_RATING, DEFAULT_RATING, score=1.0, k_factor=32.0)
    decayed = decay_for_inactivity(settled, weeks_since_last_game=100)
    assert decayed.deviation <= DEFAULT_RATING.deviation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rating.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffanalytics.rating'`

- [ ] **Step 3: Write `src/ffanalytics/rating.py`**

```python
"""Elo/Glicko-style rating with explicit uncertainty (deviation) and
time-decay — adapted from the DISCIPLINE of ~/projects/sports-analytics'
core/elo.py, not its code (that file's math is tennis-serve-specific).
Used for both whole-team strength and per-(team, position_group) matchup
strength — same math, different granularity of what "a game" means for
the position-group track (see design spec)."""

from dataclasses import dataclass

@dataclass(frozen=True)
class Rating:
    value: float
    deviation: float

DEFAULT_RATING = Rating(1500.0, 350.0)

_Q = 0.0057565  # ln(10)/400, standard Glicko constant
_MIN_DEVIATION = 50.0
_MAX_DEVIATION = 350.0
_INACTIVITY_GROWTH_PER_WEEK = 15.0  # tuned in shadow mode once real data exists


def _expected_score(a: Rating, b: Rating) -> float:
    return 1.0 / (1.0 + 10 ** ((b.value - a.value) / 400.0))


def update(current: Rating, opponent: Rating, score: float, k_factor: float) -> Rating:
    expected = _expected_score(current, opponent)
    new_value = current.value + k_factor * (score - expected)
    # deviation shrinks toward the floor as more games accumulate
    new_deviation = max(_MIN_DEVIATION, current.deviation * 0.9)
    return Rating(new_value, new_deviation)


def decay_for_inactivity(current: Rating, weeks_since_last_game: int) -> Rating:
    grown = current.deviation + _INACTIVITY_GROWTH_PER_WEEK * weeks_since_last_game
    return Rating(current.value, min(_MAX_DEVIATION, grown))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rating.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ffanalytics/rating.py tests/test_rating.py
git commit -m "feat: Glicko-2-style rating engine w/ inactivity decay"
```

---

### Task 7: Conformal prediction module

**Files:**
- Create: `src/ffanalytics/conformal.py`
- Test: `tests/test_conformal.py`

**Interfaces:**
- Produces: `conformal.qhat(residuals: list[float], alpha: float = 0.2) -> float`
  (the conformal quantile — width of the calibrated interval at `1-alpha`
  coverage, e.g. `alpha=0.2` → 80% coverage, matching the design spec's
  example), `conformal.interval(point_estimate: float, residuals: list[float], alpha: float = 0.2) -> tuple[float, float]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_conformal.py
import pytest
from ffanalytics.conformal import qhat, interval

def test_qhat_all_zero_residuals_is_zero():
    assert qhat([0.0, 0.0, 0.0], alpha=0.2) == pytest.approx(0.0)

def test_qhat_increases_with_residual_spread():
    tight = qhat([1.0, 1.0, 1.0, 1.0, 1.0], alpha=0.2)
    wide = qhat([1.0, 2.0, 5.0, 8.0, 10.0], alpha=0.2)
    assert wide > tight

def test_qhat_empty_residuals_raises():
    with pytest.raises(ValueError, match="residuals"):
        qhat([], alpha=0.2)

def test_interval_is_symmetric_around_point_estimate():
    lo, hi = interval(14.2, [1.0, 2.0, 3.0, 4.0], alpha=0.2)
    width = qhat([1.0, 2.0, 3.0, 4.0], alpha=0.2)
    assert lo == pytest.approx(14.2 - width)
    assert hi == pytest.approx(14.2 + width)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_conformal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffanalytics.conformal'`

- [ ] **Step 3: Write `src/ffanalytics/conformal.py`**

```python
"""Split conformal prediction for calibrated confidence intervals —
adapted from ~/projects/sports-analytics' core/math.py `conformal_qhat`
pattern. Turns a bare point projection into a calibrated interval, per
design spec's start/sit "confident vs. it's close" distinction."""

import math


def qhat(residuals: list[float], alpha: float = 0.2) -> float:
    if not residuals:
        raise ValueError("residuals must be non-empty to compute qhat")
    abs_residuals = sorted(abs(r) for r in residuals)
    n = len(abs_residuals)
    # standard split-conformal finite-sample correction
    rank = math.ceil((n + 1) * (1 - alpha))
    rank = min(rank, n)
    return abs_residuals[rank - 1]


def interval(point_estimate: float, residuals: list[float], alpha: float = 0.2) -> tuple[float, float]:
    width = qhat(residuals, alpha=alpha)
    return (point_estimate - width, point_estimate + width)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_conformal.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ffanalytics/conformal.py tests/test_conformal.py
git commit -m "feat: split conformal prediction for calibrated projection intervals"
```

---

### Task 8: Shadow logger

**Files:**
- Create: `src/ffanalytics/shadow.py`
- Test: `tests/test_shadow.py`

**Interfaces:**
- Consumes: `db.get_connection`, `db.init_schema`
- Produces: `shadow.log_recommendation(conn, kind: str, season: int, week: int, player_id: str | None, recommendation: dict, logged_at_iso: str) -> int`
  (returns the new row id), `shadow.record_outcome(conn, recommendation_id: int, actual_outcome: dict) -> None`,
  `shadow.count_logged(conn, kind: str) -> int` (for the "enough samples
  before promoting a heuristic" gate — exact threshold constant lives in
  `config.py`, added in this task: `config.MIN_SHADOW_SAMPLES = 20` as a
  starting placeholder value, documented as revisit-once-real-data-exists,
  mirroring `MIN_MUESTRA_SHADOW` from the reference repo)

- [ ] **Step 1: Add `MIN_SHADOW_SAMPLES` to config**

In `src/ffanalytics/config.py`, add:

```python
# Minimum logged+resolved shadow samples before a new heuristic can be
# promoted to a live recommendation. Starting value only — revisit once
# real recommendation volume/variance is known (mirrors reference repo's
# MIN_MUESTRA_SHADOW, which was tuned empirically, not guessed).
MIN_SHADOW_SAMPLES = 20
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_shadow.py
import json
import tempfile
from pathlib import Path

from ffanalytics import db, shadow

def _fresh_conn():
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "test.db"
    conn = db.get_connection(path)
    db.init_schema(conn)
    return conn, tmp  # keep tmp alive for the test's duration

def test_log_and_count():
    conn, tmp = _fresh_conn()
    rec_id = shadow.log_recommendation(
        conn, kind="start_sit", season=2026, week=1, player_id="4046",
        recommendation={"start": True, "projected": 14.2},
        logged_at_iso="2026-09-10T12:00:00",
    )
    assert isinstance(rec_id, int)
    assert shadow.count_logged(conn, kind="start_sit") == 1
    assert shadow.count_logged(conn, kind="waiver") == 0
    conn.close()

def test_record_outcome_updates_row():
    conn, tmp = _fresh_conn()
    rec_id = shadow.log_recommendation(
        conn, kind="start_sit", season=2026, week=1, player_id="4046",
        recommendation={"start": True, "projected": 14.2},
        logged_at_iso="2026-09-10T12:00:00",
    )
    shadow.record_outcome(conn, rec_id, {"actual_points": 16.9})
    row = conn.execute(
        "SELECT actual_outcome FROM shadow_recommendations WHERE id = ?", (rec_id,)
    ).fetchone()
    assert json.loads(row["actual_outcome"]) == {"actual_points": 16.9}
    conn.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_shadow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffanalytics.shadow'`

- [ ] **Step 4: Write `src/ffanalytics/shadow.py`**

```python
"""Shadow-mode logging — every recommendation the decision layer produces
is logged here with its inputs and (later) the actual outcome, so a new
heuristic can be backtested before it's trusted live. Mirrors the
reference repo's shadow.py / evaluacion.py discipline."""

import json
import sqlite3


def log_recommendation(
    conn: sqlite3.Connection,
    kind: str,
    season: int,
    week: int,
    player_id: str | None,
    recommendation: dict,
    logged_at_iso: str,
) -> int:
    cursor = conn.execute(
        """INSERT INTO shadow_recommendations
           (kind, season, week, player_id, recommendation, logged_at, actual_outcome)
           VALUES (?, ?, ?, ?, ?, ?, NULL)""",
        (kind, season, week, player_id, json.dumps(recommendation), logged_at_iso),
    )
    conn.commit()
    return cursor.lastrowid


def record_outcome(conn: sqlite3.Connection, recommendation_id: int, actual_outcome: dict) -> None:
    conn.execute(
        "UPDATE shadow_recommendations SET actual_outcome = ? WHERE id = ?",
        (json.dumps(actual_outcome), recommendation_id),
    )
    conn.commit()


def count_logged(conn: sqlite3.Connection, kind: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM shadow_recommendations WHERE kind = ?", (kind,)
    ).fetchone()
    return row["n"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_shadow.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/ffanalytics/config.py src/ffanalytics/shadow.py tests/test_shadow.py
git commit -m "feat: shadow-mode recommendation logger"
```

---

### Task 9: FastAPI app — health + refresh endpoints

**Files:**
- Create: `src/ffanalytics/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: nothing new beyond stdlib/FastAPI
- Produces: `api.app` (FastAPI instance) with `GET /health -> {"status": "ok"}`
  and `POST /refresh -> {"status": "accepted"}` (stub for now — Task 10 wires
  it to real adapters via a `run_refresh` callable the route delegates to,
  so this task's test doesn't need network mocking)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from ffanalytics.api import app

client = TestClient(app)

def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

def test_refresh_endpoint_accepted():
    resp = client.post("/refresh")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffanalytics.api'`

- [ ] **Step 3: Write `src/ffanalytics/api.py`**

```python
"""FastAPI app, run locally only (uvicorn on localhost — no public
hosting, see design spec's hosting decision). In-memory cache pattern
follows the reference repo's api.py: refresh populates a module-level
cache, request handlers read from it, never touching disk per-request."""

from fastapi import FastAPI

app = FastAPI(title="Fantasy Football Analytics Engine")

_CACHE: dict = {}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/refresh")
def refresh() -> dict:
    # Task 10 replaces this stub body with a call into a run_refresh()
    # that populates _CACHE from the three adapters + rating engine.
    return {"status": "accepted"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/ffanalytics/api.py tests/test_api.py
git commit -m "feat: FastAPI app skeleton with health + refresh stub"
```

---

### Task 10: Wire refresh job (adapters → SQLite, stale-cache fallback)

**Files:**
- Create: `src/ffanalytics/refresh.py`
- Modify: `src/ffanalytics/api.py` (POST /refresh calls `refresh.run_refresh`)
- Test: `tests/test_refresh.py`

**Interfaces:**
- Consumes: `adapters.sleeper.get_league_settings/get_rosters/get_injury_statuses`,
  `adapters.nflverse.get_weekly_player_stats`, `db.get_connection`, `db.init_schema`
- Produces: `refresh.run_refresh(conn, season: int, sleeper_session=None, nfl_module=None, ran_at_iso: str) -> dict`
  (returns a summary dict `{"sleeper": bool, "nflverse": bool}` indicating
  per-source success; on failure of a source, logs to `refresh_log` and
  keeps going rather than raising — matches spec's "keep serving last
  successful cache" rule, since a raised exception here would abort the
  whole refresh instead of doing the sources that DID succeed)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_refresh.py
import tempfile
from pathlib import Path
from unittest.mock import Mock

from ffanalytics import db, refresh


def _fresh_conn():
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "test.db"
    conn = db.get_connection(path)
    db.init_schema(conn)
    return conn, tmp


def test_run_refresh_all_sources_succeed():
    conn, tmp = _fresh_conn()
    sleeper_session = Mock()
    league_resp = Mock()
    league_resp.json.return_value = {
        "scoring_settings": {"rec": 1.0}, "roster_positions": ["QB"]
    }
    league_resp.raise_for_status.return_value = None
    rosters_resp = Mock()
    rosters_resp.json.return_value = [{"roster_id": 1}]
    rosters_resp.raise_for_status.return_value = None
    players_resp = Mock()
    players_resp.json.return_value = {}
    players_resp.raise_for_status.return_value = None
    sleeper_session.get.side_effect = [league_resp, rosters_resp, players_resp]

    fake_nfl = Mock()
    class _Frame:
        def to_dicts(self):
            return [{"player_id": "4046", "target_share": 0.3}]
    fake_nfl.load_player_stats.return_value = _Frame()

    result = refresh.run_refresh(
        conn, season=2026, sleeper_session=sleeper_session, nfl_module=fake_nfl,
        ran_at_iso="2026-09-10T09:00:00",
    )
    assert result == {"sleeper": True, "nflverse": True}
    rows = conn.execute("SELECT source, success FROM refresh_log").fetchall()
    assert {(r["source"], r["success"]) for r in rows} == {
        ("sleeper", 1), ("nflverse", 1)
    }
    conn.close()


def test_run_refresh_nflverse_failure_logs_and_continues():
    conn, tmp = _fresh_conn()
    sleeper_session = Mock()
    league_resp = Mock()
    league_resp.json.return_value = {"scoring_settings": {}, "roster_positions": []}
    league_resp.raise_for_status.return_value = None
    rosters_resp = Mock()
    rosters_resp.json.return_value = []
    rosters_resp.raise_for_status.return_value = None
    players_resp = Mock()
    players_resp.json.return_value = {}
    players_resp.raise_for_status.return_value = None
    sleeper_session.get.side_effect = [league_resp, rosters_resp, players_resp]

    fake_nfl = Mock()
    fake_nfl.load_player_stats.side_effect = ConnectionError("boom")

    result = refresh.run_refresh(
        conn, season=2026, sleeper_session=sleeper_session, nfl_module=fake_nfl,
        ran_at_iso="2026-09-10T09:00:00",
    )
    assert result == {"sleeper": True, "nflverse": False}
    row = conn.execute(
        "SELECT success, error_message FROM refresh_log WHERE source = 'nflverse'"
    ).fetchone()
    assert row["success"] == 0
    assert "boom" in row["error_message"]
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_refresh.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ffanalytics.refresh'`

- [ ] **Step 3: Write `src/ffanalytics/refresh.py`**

```python
"""Refresh job: pulls from each adapter independently, logs per-source
success/failure to refresh_log, and never lets one source's failure abort
the others — matches design spec's stale-cache-fallback error handling."""

import sqlite3

from ffanalytics import config
from ffanalytics.adapters import nflverse, sleeper


def _log(conn: sqlite3.Connection, source: str, success: bool, error_message: str | None, ran_at_iso: str) -> None:
    conn.execute(
        "INSERT INTO refresh_log (source, ran_at, success, error_message) VALUES (?, ?, ?, ?)",
        (source, ran_at_iso, 1 if success else 0, error_message),
    )
    conn.commit()


def run_refresh(
    conn: sqlite3.Connection,
    season: int,
    sleeper_session=None,
    nfl_module=None,
    ran_at_iso: str = "",
) -> dict:
    result = {}

    try:
        sleeper.get_league_settings(config.LEAGUE_ID, session=sleeper_session)
        sleeper.get_rosters(config.LEAGUE_ID, session=sleeper_session)
        sleeper.get_injury_statuses(session=sleeper_session)
        _log(conn, "sleeper", True, None, ran_at_iso)
        result["sleeper"] = True
    except Exception as exc:
        _log(conn, "sleeper", False, str(exc), ran_at_iso)
        result["sleeper"] = False

    try:
        nflverse.get_weekly_player_stats(season, nfl_module=nfl_module)
        _log(conn, "nflverse", True, None, ran_at_iso)
        result["nflverse"] = True
    except Exception as exc:
        _log(conn, "nflverse", False, str(exc), ran_at_iso)
        result["nflverse"] = False

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_refresh.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire `POST /refresh` to `run_refresh`**

In `src/ffanalytics/api.py`, replace the refresh stub:

```python
from ffanalytics import db, refresh as refresh_module

@app.post("/refresh")
def refresh() -> dict:
    conn = db.get_connection()
    db.init_schema(conn)
    import datetime
    ran_at_iso = datetime.datetime.now().isoformat()
    result = refresh_module.run_refresh(conn, season=datetime.datetime.now().year, ran_at_iso=ran_at_iso)
    conn.close()
    return {"status": "accepted", "sources": result}
```

- [ ] **Step 6: Run full test suite to confirm nothing broke**

Run: `pytest -v`
Expected: all tests pass (existing `/refresh` test in `tests/test_api.py`
still checks only `status == "accepted"`, which still holds)

- [ ] **Step 7: Commit**

```bash
git add src/ffanalytics/refresh.py src/ffanalytics/api.py tests/test_refresh.py
git commit -m "feat: wire refresh job to adapters with per-source failure isolation"
```

---

### Task 11: launchd scheduling script

**Files:**
- Create: `scripts/refresh_job.sh`
- Create: `scripts/com.ffanalytics.refresh.plist`
- Create: `docs/RUNBOOK.md`

**Interfaces:** none (operational glue, no importable code)

- [ ] **Step 1: Write `scripts/refresh_job.sh`**

```bash
#!/bin/bash
# Called by launchd daily during the NFL season. Hits the local API's
# /refresh endpoint — assumes `uvicorn ffanalytics.api:app` is already
# running (see docs/RUNBOOK.md for the manual-fallback command if it isn't).
set -euo pipefail
curl -sf -X POST http://localhost:8000/refresh || {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) refresh failed — is the server running?" >&2
    exit 1
}
```

- [ ] **Step 2: `chmod +x scripts/refresh_job.sh`**

Run: `chmod +x scripts/refresh_job.sh`

- [ ] **Step 3: Write `scripts/com.ffanalytics.refresh.plist`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ffanalytics.refresh</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>REPLACE_WITH_ABSOLUTE_PATH/scripts/refresh_job.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardErrorPath</key>
    <string>REPLACE_WITH_ABSOLUTE_PATH/logs/refresh.err.log</string>
    <key>StandardOutPath</key>
    <string>REPLACE_WITH_ABSOLUTE_PATH/logs/refresh.out.log</string>
</dict>
</plist>
```

- [ ] **Step 4: Write `docs/RUNBOOK.md`**

```markdown
# Runbook

## Start the API locally
`uvicorn ffanalytics.api:app --reload` (dev) or without `--reload` (daily use)

**Never** add `--host 0.0.0.0` or any tunnel/port-forward — uvicorn's default
`127.0.0.1` binding is what keeps this off the internet entirely. If you ever
want remote access (phone, etc.), that's a deliberate future decision, not a
flag to add here.

## Install the daily refresh job
1. Replace `REPLACE_WITH_ABSOLUTE_PATH` in `scripts/com.ffanalytics.refresh.plist`
   with this repo's absolute path (twice, plus the logs dir).
2. `mkdir -p logs`
3. `cp scripts/com.ffanalytics.refresh.plist ~/Library/LaunchAgents/`
4. `launchctl load ~/Library/LaunchAgents/com.ffanalytics.refresh.plist`

## Manual refresh fallback
If the laptop was asleep/closed at 7am and the launchd job didn't fire:
`curl -X POST http://localhost:8000/refresh`

## Uninstall the job
`launchctl unload ~/Library/LaunchAgents/com.ffanalytics.refresh.plist`
```

- [ ] **Step 5: Commit**

```bash
git add scripts/refresh_job.sh scripts/com.ffanalytics.refresh.plist docs/RUNBOOK.md
git commit -m "chore: launchd daily refresh scheduling + runbook"
```

---

## Deferred to a follow-up plan (explicitly out of scope here)

Per the design spec's "Out of scope (v1)" and to keep this plan reviewable:
the **decision layer** (start/sit ranking, waiver priority, trade evaluation
— consuming `rating.py` + `conformal.py` + `shadow.py` together) and the
**projection engine** that turns raw stats into a point estimate are
substantial enough to warrant their own plan once Tasks 1–11 are reviewed
and merged. Flagging this now rather than silently expanding scope — this
plan delivers a working, testable data + rating + logging foundation; the
decision layer is the natural next plan.
