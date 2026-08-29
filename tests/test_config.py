import os
import pytest

def test_league_id_missing_raises(monkeypatch):
    import importlib
    import ffanalytics.config as config_module
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "")
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
