"""
tests/test_location_resolver.py

Tests for LocationResolver covering:
- Explicit city geocoding
- Current-location phrases (must NOT geocode)
- Geocoding failure → GPS fallback
- Missing GPS + failed geocoding → None
- Invalid coordinate rejection
- Reverse-geocode failure preserves coordinates
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from services.location_resolver import LocationResolver, CURRENT_LOCATION_PHRASES


@pytest.fixture
def resolver():
    return LocationResolver()


# ---------------------------------------------------------------------------
# Helper — build an httpx response mock
# ---------------------------------------------------------------------------
def _mock_geocode_response(lat, lon, name="TestCity"):
    """Returns a mock that looks like a successful Open-Meteo geocoding response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [{"latitude": lat, "longitude": lon, "name": name}]
    }
    return mock_resp


def _mock_empty_geocode_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": []}
    return mock_resp


def _mock_nominatim_response(city="TestCity"):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"address": {"city": city}}
    return mock_resp


# ---------------------------------------------------------------------------
# Test 1: Explicit city geocoding succeeds
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_explicit_city_geocoded(resolver):
    """Explicit city name should be geocoded to lat/lon."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=_mock_geocode_response(11.0168, 76.9558, "Coimbatore"))

        result = await resolver.resolve(user_location="coimbatore")

    assert result is not None
    assert result["source"] == "user_input"
    assert abs(result["lat"] - 11.0168) < 0.01
    assert abs(result["lon"] - 76.9558) < 0.01


# ---------------------------------------------------------------------------
# Test 2: Current-location phrases must NOT be geocoded
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", [
    "near me", "my area", "my location", "here", "nearby",
    "current location", "weather in my area", "local weather",
])
async def test_current_location_phrases_use_gps(resolver, phrase):
    """
    Generic current-location phrases must bypass geocoding and use browser GPS.
    """
    gps_lat, gps_lon = 11.0168, 76.9558

    with patch.object(resolver, "_geocode", new_callable=AsyncMock) as mock_geo:
        result = await resolver.resolve(
            user_location=phrase,
            frontend_lat=gps_lat,
            frontend_lon=gps_lon,
        )

    # _geocode must NOT have been called for these phrases
    mock_geo.assert_not_called()
    assert result is not None
    assert result["source"] == "browser_geolocation"
    assert abs(result["lat"] - gps_lat) < 0.001
    assert abs(result["lon"] - gps_lon) < 0.001


# ---------------------------------------------------------------------------
# Test 3: Geocoding failure falls back to browser GPS
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_geocode_failure_falls_back_to_gps(resolver):
    """If city geocoding fails, browser GPS should be used as fallback."""
    gps_lat, gps_lon = 13.0827, 80.2707

    with patch.object(resolver, "_geocode", new_callable=AsyncMock, return_value=(None, None)):
        with patch.object(resolver, "_reverse_geocode", new_callable=AsyncMock, return_value="Chennai"):
            result = await resolver.resolve(
                user_location="unknownmadecupplace",
                frontend_lat=gps_lat,
                frontend_lon=gps_lon,
            )

    assert result is not None
    assert result["source"] == "browser_geolocation"
    assert abs(result["lat"] - gps_lat) < 0.001


# ---------------------------------------------------------------------------
# Test 4: No GPS and geocoding fails → None
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_location_returns_none(resolver):
    """When neither GPS nor city geocoding is available, return None."""
    with patch.object(resolver, "_geocode", new_callable=AsyncMock, return_value=(None, None)):
        result = await resolver.resolve(
            user_location="unknownplace",
            frontend_lat=None,
            frontend_lon=None,
        )

    assert result is None


# ---------------------------------------------------------------------------
# Test 5: Invalid coordinates are rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("lat,lon", [
    (float("nan"), 80.0),
    (91.0, 80.0),       # lat out of range
    (11.0, 181.0),      # lon out of range
    (None, 80.0),
    (11.0, None),
])
async def test_invalid_gps_coords_rejected(resolver, lat, lon):
    """
    Invalid GPS coordinates must not be used. Resolver should return None
    if the GPS coords are the only source and they are invalid.
    """
    result = await resolver.resolve(
        user_location=None,
        frontend_lat=lat,
        frontend_lon=lon,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Test 6: Reverse-geocode failure preserves valid coordinates
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reverse_geocode_failure_preserves_coords(resolver):
    """
    If reverse geocoding fails (city name lookup), the lat/lon should still
    be usable — the result should not be discarded.
    """
    gps_lat, gps_lon = 11.0168, 76.9558

    with patch.object(resolver, "_reverse_geocode", new_callable=AsyncMock, return_value="Your Location"):
        result = await resolver.resolve(
            user_location=None,
            frontend_lat=gps_lat,
            frontend_lon=gps_lon,
        )

    assert result is not None, "Coordinates should be usable even if city name lookup failed"
    assert result["lat"] == gps_lat
    assert result["lon"] == gps_lon
    assert result["city"] == "Your Location"


# ---------------------------------------------------------------------------
# Test 7: GPS-only query (no text location)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_gps_only_used_when_no_text_location(resolver):
    gps_lat, gps_lon = 28.6139, 77.2090

    with patch.object(resolver, "_reverse_geocode", new_callable=AsyncMock, return_value="New Delhi"):
        result = await resolver.resolve(
            user_location=None,
            frontend_lat=gps_lat,
            frontend_lon=gps_lon,
        )

    assert result is not None
    assert result["source"] == "browser_geolocation"
    assert result["city"] == "New Delhi"
