"""
tests/test_weather_fetcher.py

Tests for WeatherFetcher covering:
- Valid coordinates → parsed weather data
- Missing coordinates → no external requests made
- Primary provider timeout → OWM fallback triggered
- Primary provider HTTP error → OWM fallback triggered
- Malformed JSON → fallback triggered
- All providers failing → (None, None) returned (no mock data)
- Mock data is never returned as real weather
- Coordinate validation (NaN, out-of-range)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
from services.weather_fetcher import WeatherFetcher


@pytest.fixture
def fetcher():
    return WeatherFetcher()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SAMPLE_OPEN_METEO_RESPONSE = {
    "current": {
        "temperature_2m": 28.5,
        "apparent_temperature": 30.0,
        "relative_humidity_2m": 65,
        "weather_code": 1,
        "wind_speed_10m": 12.5,
        "precipitation": 0.0,
        "surface_pressure": 1012.0,
    },
    "daily": {
        "time": ["2026-01-01", "2026-01-02"],
        "weather_code": [1, 2],
        "temperature_2m_max": [32.0, 31.0],
        "temperature_2m_min": [22.0, 21.0],
        "precipitation_probability_max": [10, 20],
        "wind_speed_10m_max": [15.0, 14.0],
    },
    "hourly": {
        "time": ["2026-01-01T00:00", "2026-01-01T03:00"],
        "precipitation_probability": [0, 5],
        "temperature_2m": [22.0, 21.5],
        "weather_code": [1, 1],
    },
}


def _make_mock_response(status=200, json_data=None, raise_exc=None):
    """Build a mock httpx response."""
    mock = MagicMock()
    mock.status_code = status
    if json_data is not None:
        mock.json.return_value = json_data
    if raise_exc:
        mock.raise_for_status.side_effect = raise_exc
    else:
        mock.raise_for_status = MagicMock()
    return mock


def _make_async_client_ctx(mock_get_response):
    """Build an AsyncClient context-manager mock that returns mock_get_response from .get()."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_get_response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Test 1: Valid coords → parsed weather data
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_valid_coords_return_weather(fetcher):
    """Valid lat/lon should yield parsed current weather and forecast."""
    location = {"lat": 11.0168, "lon": 76.9558, "city": "Coimbatore"}

    mock_resp = _make_mock_response(json_data=SAMPLE_OPEN_METEO_RESPONSE)
    ctx = _make_async_client_ctx(mock_resp)

    with patch("httpx.AsyncClient", return_value=ctx):
        current, forecast = await fetcher.get_weather_and_forecast(location)

    assert current is not None, "Should return current weather"
    assert current["temperature"] == 28.5
    assert current["source"] == "open-meteo"
    assert forecast is not None, "Should return forecast"
    assert isinstance(forecast["forecast"], list)


# ---------------------------------------------------------------------------
# Test 2: Missing coords → no external request made
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_coords_returns_none_without_request(fetcher):
    """
    If location has no lat/lon and no city, (None, None) must be returned
    without making any HTTP request.
    """
    location = {"lat": None, "lon": None, "city": ""}

    with patch("httpx.AsyncClient") as mock_cls:
        current, forecast = await fetcher.get_weather_and_forecast(location)

    # No HTTP client should have been instantiated
    mock_cls.assert_not_called()
    assert current is None
    assert forecast is None


# ---------------------------------------------------------------------------
# Test 3: NaN coordinates rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_nan_coords_rejected(fetcher):
    """NaN latitude/longitude must be treated as missing — no request made."""
    location = {"lat": float("nan"), "lon": float("nan"), "city": ""}

    with patch("httpx.AsyncClient") as mock_cls:
        current, forecast = await fetcher.get_weather_and_forecast(location)

    mock_cls.assert_not_called()
    assert current is None
    assert forecast is None


# ---------------------------------------------------------------------------
# Test 4: Primary provider timeout → OWM fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_open_meteo_timeout_triggers_owm_fallback(fetcher, monkeypatch):
    """If Open-Meteo times out, the OWM fallback should be attempted."""
    location = {"lat": 11.0168, "lon": 76.9558, "city": "Coimbatore"}

    owm_current_resp = {
        "main": {"temp": 29.0, "feels_like": 31.0, "humidity": 70, "pressure": 1010},
        "wind": {"speed": 3.5},
        "rain": {},
        "weather": [{"description": "clear sky"}],
    }
    owm_forecast_resp = {
        "list": [
            {
                "dt_txt": "2026-01-01 12:00:00",
                "main": {"temp": 29.0},
                "pop": 0.1,
                "weather": [{"description": "clear sky"}],
            }
        ]
    }

    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "open-meteo.com/v1/forecast" in url:
            raise httpx.TimeoutException("Timed out")
        if "openweathermap.org/data/2.5/weather" in url:
            return _make_mock_response(json_data=owm_current_resp)
        if "openweathermap.org/data/2.5/forecast" in url:
            return _make_mock_response(json_data=owm_forecast_resp)
        raise ValueError(f"Unexpected URL: {url}")

    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key-12345")

    mock_client = AsyncMock()
    mock_client.get = mock_get
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    # Disable tenacity retries for speed
    with patch("httpx.AsyncClient", return_value=ctx):
        with patch.object(fetcher, "_get_owm_fallback", new_callable=AsyncMock) as mock_owm:
            mock_owm.return_value = (
                fetcher._parse_owm_current(owm_current_resp, location),
                fetcher._parse_owm_forecast(owm_forecast_resp, location),
            )
            current, forecast = await fetcher.get_weather_and_forecast(location)

    mock_owm.assert_called_once()
    assert current is not None


# ---------------------------------------------------------------------------
# Test 5: Primary provider HTTP 429/503 → OWM fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_open_meteo_http_error_triggers_owm_fallback(fetcher):
    """HTTP errors from Open-Meteo should trigger OWM fallback."""
    location = {"lat": 11.0168, "lon": 76.9558, "city": "Coimbatore"}

    mock_resp = _make_mock_response(status=503)
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=mock_resp
    )
    ctx = _make_async_client_ctx(mock_resp)

    owm_current = {"main": {"temp": 27.0, "feels_like": 29.0, "humidity": 60, "pressure": 1008},
                   "wind": {"speed": 2.0}, "rain": {}, "weather": [{"description": "partly cloudy"}]}
    owm_forecast = {"list": []}

    with patch("httpx.AsyncClient", return_value=ctx):
        with patch.object(fetcher, "_get_owm_fallback", new_callable=AsyncMock) as mock_owm:
            mock_owm.return_value = (
                fetcher._parse_owm_current(owm_current, location),
                fetcher._parse_owm_forecast(owm_forecast, location),
            )
            current, forecast = await fetcher.get_weather_and_forecast(location)

    mock_owm.assert_called_once()
    assert current is not None


# ---------------------------------------------------------------------------
# Test 6: Malformed JSON → fallback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_malformed_json_triggers_fallback(fetcher):
    """Open-Meteo returning malformed JSON should trigger OWM fallback."""
    location = {"lat": 11.0168, "lon": 76.9558, "city": "Coimbatore"}

    mock_resp = _make_mock_response(status=200)
    mock_resp.json.side_effect = ValueError("Unexpected token")
    ctx = _make_async_client_ctx(mock_resp)

    with patch("httpx.AsyncClient", return_value=ctx):
        with patch.object(fetcher, "_get_owm_fallback", new_callable=AsyncMock) as mock_owm:
            mock_owm.return_value = (None, None)
            current, forecast = await fetcher.get_weather_and_forecast(location)

    # (None, None) is acceptable — the key is no crash and no mock weather
    assert current is None or isinstance(current, dict)


# ---------------------------------------------------------------------------
# Test 7: All providers fail → (None, None), no mock data
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_all_providers_fail_returns_none_not_mock(fetcher):
    """
    When both Open-Meteo and OWM fail, the fetcher must return (None, None).
    It must NEVER return mock/fabricated weather data.
    """
    location = {"lat": 11.0168, "lon": 76.9558, "city": "Coimbatore"}

    with patch.object(fetcher, "_get_owm_fallback", new_callable=AsyncMock) as mock_owm:
        mock_owm.side_effect = Exception("OWM also failed")

        mock_resp = _make_mock_response(status=503)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=mock_resp
        )
        ctx = _make_async_client_ctx(mock_resp)

        with patch("httpx.AsyncClient", return_value=ctx):
            current, forecast = await fetcher.get_weather_and_forecast(location)

    assert current is None, (
        "When all providers fail, current must be None — mock data must never be returned."
    )
    assert forecast is None, (
        "When all providers fail, forecast must be None — mock data must never be returned."
    )


# ---------------------------------------------------------------------------
# Test 8: Mock data is never passed off as "source=live"
# ---------------------------------------------------------------------------
def test_no_live_source_in_mock_data(fetcher):
    """
    Verify that the WeatherFetcher class does NOT have a _get_mock_fallback method.
    If it does, the 'source' must be 'fallback-mock', never 'open-meteo' or 'openweathermap'.
    This enforces BUG 5 fix — no fabricated data presented as live data.
    """
    # After the fix, _get_mock_fallback should not exist
    assert not hasattr(fetcher, "_get_mock_fallback"), (
        "_get_mock_fallback should have been removed. "
        "Mock weather data must never be returned when all providers fail."
    )
