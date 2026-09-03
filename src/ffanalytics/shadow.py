"""Shadow-mode logging: every recommendation is recorded with inputs and
(later) actual outcome so new heuristics can be backtested before going live."""

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


def log_recommendations_batch(
    conn: sqlite3.Connection,
    recs: list[dict],
) -> int:
    if not recs:
        return 0
    try:
        rows = []
        for r in recs:
            rows.append((
                r["kind"],
                r["season"],
                r["week"],
                r.get("player_id"),
                json.dumps(r["recommendation"]),
                r["logged_at"],
            ))
        conn.executemany(
            """INSERT INTO shadow_recommendations
               (kind, season, week, player_id, recommendation, logged_at, actual_outcome)
               VALUES (?, ?, ?, ?, ?, ?, NULL)""",
            rows,
        )
        conn.commit()
        return len(rows)
    except Exception:
        return 0


def record_outcome(conn: sqlite3.Connection, recommendation_id: int, actual_outcome: dict) -> None:
    conn.execute(
        "UPDATE shadow_recommendations SET actual_outcome = ? WHERE id = ?",
        (json.dumps(actual_outcome), recommendation_id),
    )
    conn.commit()


def evaluate_unresolved_shadow_recommendations(
    conn: sqlite3.Connection,
    player_stats: list[dict],
    scoring_settings: dict | None = None,
) -> int:
    from ffanalytics.scoring import calculate_fantasy_points

    if not player_stats:
        return 0

    rows = conn.execute(
        "SELECT id, season, week, player_id FROM shadow_recommendations WHERE actual_outcome IS NULL AND player_id IS NOT NULL"
    ).fetchall()

    if not rows:
        return 0

    actuals = {}
    for p in player_stats:
        pid = str(p.get("player_id") or p.get("id") or "")
        wk = p.get("week")
        if pid and wk:
            fpts = p.get("fantasy_points")
            if fpts is None:
                fpts = calculate_fantasy_points(p, scoring_settings)
            actuals[(pid, int(wk))] = float(fpts)

    resolved = 0
    for r in rows:
        rec_id = r["id"]
        pid = str(r["player_id"])
        wk = r["week"]
        key = (pid, int(wk))
        if key in actuals:
            actual_pts = round(actuals[key], 2)
            record_outcome(conn, rec_id, {"actual_points": actual_pts, "week": wk})
            resolved += 1

    return resolved


def count_logged(conn: sqlite3.Connection, kind: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM shadow_recommendations WHERE kind = ?", (kind,)
    ).fetchone()
    return row["n"]


def count_resolved(conn: sqlite3.Connection, kind: str) -> int:
    """Count shadow rows with observed outcomes (actual_outcome IS NOT NULL).

    Resolved-only counting is the honest trust signal — logged-only rows have
    no outcome to backtest against. Kept separate from count_logged for
    backward compat; is_trusted() below uses resolved where outcome data
    exists (refresh.py resolves via evaluate_unresolved_shadow_recommendations).
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM shadow_recommendations WHERE kind = ? AND actual_outcome IS NOT NULL",
        (kind,),
    ).fetchone()
    return row["n"]


def is_trusted(
    conn: sqlite3.Connection,
    kind: str,
    threshold: int | None = None,
) -> bool:
    """Return True once a shadow rule has enough RESOLVED samples to trust live.

    Gate: count_resolved(conn, kind) >= threshold, where threshold defaults to
    config.MIN_SHADOW_SAMPLES (20). Switched from count_logged to
    count_resolved — logged-only rows have no outcome to validate against;
    where outcome data exists (refresh.py resolves via player_stats) resolved
    is the honest signal. If no resolved rows exist yet (fresh DB, outcome
    pipeline never ran), this returns False and callers fall back to baseline
    + log (see decision.py gated wrappers). Non-breaking helper — no existing
    callers changed.

    Integration point for backend (do NOT edit decision.py here):
    decision.py should wrap any promotion of a shadow `kind` to live with::

        from ffanalytics import shadow
        if not shadow.is_trusted(conn, kind="start_sit"):
            # stay on baseline / keep shadow-only; do not promote
            ...

    Wire `threshold` explicitly in tests to avoid DB/config coupling.
    """
    if threshold is None:
        try:
            from ffanalytics import config

            threshold = int(config.MIN_SHADOW_SAMPLES)
        except Exception:
            threshold = 20
    try:
        return count_resolved(conn, kind) >= int(threshold)
    except Exception:
        return False