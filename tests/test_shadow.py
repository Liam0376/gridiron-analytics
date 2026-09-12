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

def test_evaluate_unresolved_shadow_recommendations():
    conn, tmp = _fresh_conn()
    rec_id = shadow.log_recommendation(
        conn, kind="start_sit", season=2026, week=1, player_id="4046",
        recommendation={"start": True, "projected": 14.2},
        logged_at_iso="2026-09-10T12:00:00",
    )
    player_stats = [
        {"player_id": "4046", "week": 1, "fantasy_points": 18.5}
    ]
    count = shadow.evaluate_unresolved_shadow_recommendations(conn, player_stats)
    assert count == 1
    row = conn.execute(
        "SELECT actual_outcome FROM shadow_recommendations WHERE id = ?", (rec_id,)
    ).fetchone()
    assert json.loads(row["actual_outcome"]) == {"actual_points": 18.5, "week": 1}
    conn.close()


def test_batch_failure_reports_input_count():
    # why (correctness batch 2026-09-12): first-row KeyError reported
    # 0 rows lost for 1 input via len(rows). Must report len(recs).
    import logging
    conn, tmp = _fresh_conn()
    bad = [{"season": 2026, "week": 1}]  # missing kind -> KeyError
    records = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r.getMessage())  # type: ignore
    logger = logging.getLogger("ffanalytics.shadow")
    logger.addHandler(handler)
    try:
        out = shadow.log_recommendations_batch(conn, bad)
    finally:
        logger.removeHandler(handler)
    assert out == 0
    assert any("1 rows lost" in m for m in records)
    conn.close()