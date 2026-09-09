import os
import pytest


def test_league_id_missing_no_import_raise(monkeypatch):
    # why: multi-league — the id arrives per-request (UI setup / ?league_id= /
    # POST body), so import must never raise. Refresh paths raise at call
    # time via require_league_id instead (backend P0: old code raised
    # KeyError before its own friendly message was even reachable).
    import importlib
    import ffanalytics.config as config_module
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "")
    importlib.reload(config_module)
    assert config_module.get_league_id() == ""
    with pytest.raises(RuntimeError, match="SLEEPER_LEAGUE_ID"):
        config_module.require_league_id()
    assert config_module.require_league_id("12345") == "12345"


def test_league_db_paths(monkeypatch):
    import importlib
    import ffanalytics.config as config_module
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "1397736035240173568")
    monkeypatch.delenv("FFANALYTICS_DB_PATH", raising=False)
    importlib.reload(config_module)
    # default league keeps the legacy file (backward compat with installs).
    assert str(config_module.db_path_for_league(None)) == "data/fantasy.db"
    assert str(config_module.db_path_for_league("1397736035240173568")) == "data/fantasy.db"
    # any other league gets an isolated file inside data/.
    assert str(config_module.db_path_for_league("999")) == "data/fantasy_999.db"
    with pytest.raises(ValueError, match="invalid league id"):
        config_module.db_path_for_league("../evil")
    with pytest.raises(ValueError, match="invalid league id"):
        config_module.db_path_for_league("abc")


def test_get_feature_status_known_and_unknown(monkeypatch):
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "123")
    import importlib
    import ffanalytics.config as config_module
    importlib.reload(config_module)
    assert config_module.get_feature_status("target_share") == "included"
    with pytest.raises(KeyError):
        config_module.get_feature_status("not_a_real_feature")


def test_league_economics_default_reproduces_reference():
    # why (economy sign-off): no-arg league_economics() yielded RB24/WR24
    # against POS_REPL_COUNTS (RB28/WR32) and every legacy fallback while its
    # docstring claimed exact reproduction. Unknown shape = reference shape.
    from ffanalytics import config as config_module

    econ = config_module.league_economics()
    assert econ["repl_counts"] == config_module.POS_REPL_COUNTS
    assert econ["repl_counts"]["RB"] == 28 and econ["repl_counts"]["WR"] == 32
    assert econ["starter_pool"] == config_module.STARTER_BUDGET_POOL == 2352
    assert econ["starter_slots_total"] == 120
    assert econ["flex_slots"] == 2
