"""Open-Meteo adapter. Soft-fail by design (spec: weather is a soft-fail
feature, not a hard dependency) — returns None on any error instead of
raising, so a refresh job never blocks on this one adapter."""

from datetime import datetime, timedelta
import threading
import time

import requests

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Simple in-memory cache for weather forecasts
# Key: (lat, lon, game_time_iso) -> (timestamp, forecast_data)
_WEATHER_CACHE: dict[tuple[float, float, str], tuple[float, dict | None]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 300  # 5 minutes cache TTL


def get_forecast(lat: float, lon: float, game_time_iso: str, session=None) -> dict | None:
    """Get weather forecast for a specific location and time.

    Args:
        lat: Latitude
        lon: Longitude
        game_time_iso: Game time in ISO8601 format
        session: Optional requests session

    Returns:
        Dict with temp_f, wind_mph, precip_prob or None on error
    """
    http = session or requests
    cache_key = (lat, lon, game_time_iso)

    # Check cache first
    with _CACHE_LOCK:
        if cache_key in _WEATHER_CACHE:
            cached_time, cached_data = _WEATHER_CACHE[cache_key]
            if time.time() - cached_time < _CACHE_TTL_SECONDS:
                return cached_data

    # Cache miss or expired, fetch fresh data
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
        forecast = {
            "temp_f": data["hourly"]["temperature_2m"][closest_idx],
            "wind_mph": data["hourly"]["wind_speed_10m"][closest_idx],
            "precip_prob": data["hourly"]["precipitation_probability"][closest_idx],
        }

        # Update cache
        with _CACHE_LOCK:
            _WEATHER_CACHE[cache_key] = (time.time(), forecast)

        return forecast
    except Exception:
        return None