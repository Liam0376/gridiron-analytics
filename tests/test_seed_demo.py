"""Seed demo must write week 0, never week 1.

Live player_stats rows (week >= 1) outrank demo rows in hub queries via
`WHERE week<=cw ORDER BY season DESC, week DESC`. A week-1 demo row beats
live week-0 data until week 1 passes (2026-09-15 linkedin-ready spec, item 5).

seed_demo.py runs network calls at module level, so this test pins the
INSERT literal by parsing the source rather than executing it.
"""
import ast
import pathlib

SEED = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"


def _insert_weeks():
    """Week literals passed to INSERT INTO player_stats in seed_demo.py."""
    tree = ast.parse(SEED.read_text(encoding="utf-8"))
    weeks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for node2 in ast.walk(node):
            if (
                isinstance(node2, ast.Call)
                and isinstance(node2.func, ast.Attribute)
                and node2.func.attr == "execute"
                and node2.args
                and isinstance(node2.args[0], ast.Constant)
                and "INSERT INTO player_stats" in str(node2.args[0].value)
            ):
                # VALUES tuple args: (season, week, data) -> second arg is week
                vals = node.args
                # find the Constant week inside this insert call's args
                consts = [
                    a.value
                    for a in ast.walk(node)
                    if isinstance(a, ast.Constant)
                    and isinstance(a.value, int)
                    and not isinstance(a.value, bool)
                ]
                weeks.extend(c for c in consts if c in (0, 1))
    return weeks


def test_seed_inserts_week_zero_not_week_one():
    weeks = _insert_weeks()
    assert weeks, "no INSERT INTO player_stats found in seed_demo.py"
    assert weeks == [0], f"seed writes week(s) {weeks}; must be [0]"


def test_docstring_matches_inserted_week():
    text = SEED.read_text(encoding="utf-8")
    assert "week 0" in text.splitlines()[1], "module docstring must say week 0"
