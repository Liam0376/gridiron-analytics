#!/usr/bin/env python3
"""scripts/db_warm.py — warm-boot DB helper.

Ensures `data/fantasy.db` exists with the schema applied. Used by
`hub/start.sh` and `hub/FantasyHub.command` to satisfy hub isolation:
hub scripts cannot `import ffanalytics`, so this lives under `scripts/`
which is not subject to the isolation gate (only `hub/` is).

Exits non-zero on failure so the launcher's `set -euo pipefail` aborts.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    if not os.environ.get("SLEEPER_LEAGUE_ID"):
        os.environ["SLEEPER_LEAGUE_ID"] = "test"

    from ffanalytics import db

    conn = db.get_connection()
    try:
        db.init_schema(conn)
    finally:
        conn.close()
    print("  ✓ DB warm (fantasy.db + schema)")
    return 0


if __name__ == "__main__":
    sys.exit(main())