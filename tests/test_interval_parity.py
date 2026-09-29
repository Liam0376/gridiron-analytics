"""Floor/ceiling table + toss-up math parity: src vs hub/server.py vs hub JS.

Hub can't import ffanalytics (isolation gate), so its copies are pinned
here by text, and the JS copy is executed with node when available.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ffanalytics.decision import TOSS_UP_PROB, Z80, beat_prob
from ffanalytics.stat_projector import INTERVAL_TABLE, interval_bounds

ROOT = Path(__file__).resolve().parent.parent
SERVER = (ROOT / "hub" / "server.py").read_text()
JS = ROOT / "hub" / "src" / "lib" / "intervals.js"


def test_server_table_matches_src():
    for pos, rows in INTERVAL_TABLE.items():
        assert f'"{pos}": {rows},' in SERVER
    assert f"Z80 = {Z80}" in SERVER and f"TOSS_UP_PROB = {TOSS_UP_PROB}" in SERVER


def test_js_table_matches_src():
    text = JS.read_text()
    for pos, rows in INTERVAL_TABLE.items():
        assert f"{pos}: {[list(r) for r in rows]}," in text
    assert f"const Z80 = {Z80};" in text
    assert f"export const TOSS_UP_PROB = {TOSS_UP_PROB:.2f};" in text


CASES = [(0.0, "WR"), (1.5, "WR"), (6.0, "WR"), (12.0, "RB"), (25.0, "RB"),
         (20.0, "QB"), (35.0, "QB"), (8.0, "K"), (3.3, "TE"), (6.0, "DEF")]


def test_server_bounds_match_src():
    ns = {}
    start = SERVER.index("INTERVAL_TABLE = {")
    end = SERVER.index("# --- Vendored conformal")
    exec(SERVER[start:end], ns)
    for pts, pos in CASES:
        assert ns["interval_bounds"](pts, pos) == pytest.approx(interval_bounds(pts, pos))
    a = {"projected_points": 10.0, "projection_lower": 3.4, "projection_upper": 16.1}
    b = {"projected_points": 12.0, "projection_lower": 5.0, "projection_upper": 18.8}
    assert ns["beat_prob"](10.0, 3.4, 16.1, 12.0, 5.0, 18.8) == pytest.approx(beat_prob(a, b))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_bounds_match_src():
    script = (
        f"import {{intervalBounds, beatProb}} from '{JS.as_uri()}';"
        f"const cases = {json.dumps(CASES)};"
        "console.log(JSON.stringify({b: cases.map(([p, pos]) => intervalBounds(p, pos)),"
        "q: beatProb({weekly:10,lower:3.4,upper:16.1},{weekly:12,lower:5.0,upper:18.8})}));"
    )
    out = json.loads(subprocess.run(["node", "--input-type=module", "-e", script],
                                    capture_output=True, text=True, check=True).stdout)
    for (pts, pos), got in zip(CASES, out["b"]):
        assert got == pytest.approx(list(interval_bounds(pts, pos)))
    a = {"projected_points": 10.0, "projection_lower": 3.4, "projection_upper": 16.1}
    b = {"projected_points": 12.0, "projection_lower": 5.0, "projection_upper": 18.8}
    assert out["q"] == pytest.approx(beat_prob(a, b), abs=1e-6)
