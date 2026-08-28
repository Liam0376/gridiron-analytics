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
    with weather._CACHE_LOCK:
        weather._WEATHER_CACHE.clear()
    session = _mock_session(raises=True)
    result = weather.get_forecast(40.5, -74.0, "2026-09-14T13:05:00", session=session)
    assert result is None