import httpx
from typing import Optional, Dict
from utils.logger import get_logger

logger = get_logger("LocationResolver")

# ---------------------------------------------------------------------------
# Phrases that mean "use my current GPS location".
# These must never be geocoded as literal city names.
# ---------------------------------------------------------------------------
CURRENT_LOCATION_PHRASES = frozenset({
    "near me", "my area", "my location", "here", "nearby",
    "current location", "weather in my area", "local weather",
    "around me", "my place", "my region", "my field", "this area",
    "my farm", "my village", "my town", "near my location",
    "current area", "my current location", "my nearby",
})


def _is_current_location_phrase(text: str) -> bool:
    """Return True if the text is a generic 'near me / my area' phrase."""
    if not text:
        return False
    cleaned = text.strip().lower()
    # Direct match
    if cleaned in CURRENT_LOCATION_PHRASES:
        return True
    # Partial-phrase check (e.g. "weather in my area" normalised to "my area")
    for phrase in CURRENT_LOCATION_PHRASES:
        if phrase in cleaned:
            return True
    return False


def _is_valid_coords(lat, lon) -> bool:
    """Return True only if both lat and lon are finite numbers in valid range."""
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    import math
    return (
        math.isfinite(lat) and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    )


class LocationResolver:
    """
    Resolves user location using the following priority order:

    1. Named city typed by the user → geocode via Open-Meteo.
       If geocoding fails AND browser GPS is available, fall back to GPS.
    2. Current-location phrases ("near me", "my area", etc.)
       → use browser GPS directly (do NOT geocode).
    3. Browser GPS only (no explicit location mentioned in query).
    4. Nothing available → return None.

    NOTE: IP-based geolocation was removed because it resolves the
    *server's* location on Render/cloud, not the user's actual location.
    """

    async def resolve(
        self,
        user_location: Optional[str] = None,
        frontend_lat: Optional[float] = None,
        frontend_lon: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        Resolve location from the best available source.

        Args:
            user_location: City or region name extracted from the user's query.
            frontend_lat:  Latitude from browser geolocation API.
            frontend_lon:  Longitude from browser geolocation API.

        Returns:
            A location dict or None if no usable source exists.
        """
        has_gps = _is_valid_coords(frontend_lat, frontend_lon)

        # ── Case A: Explicit named location ───────────────────────────────────
        if user_location and not _is_current_location_phrase(user_location):
            result = await self._geocode_named_location(user_location, frontend_lat, frontend_lon, has_gps)
            if result:
                return result
            # Geocoding failed but we have GPS — fall through to GPS path below
            logger.warning(
                f"LocationResolver: Geocoding failed for '{user_location}'. "
                f"Falling back to browser GPS (available={has_gps})."
            )

        # ── Case B & C: Current-location phrase OR no explicit city → use GPS ─
        if has_gps:
            city = await self._reverse_geocode(frontend_lat, frontend_lon)
            logger.info(
                f"LocationResolver: Using browser GPS → {city} "
                f"({frontend_lat:.5f}, {frontend_lon:.5f})"
            )
            return {
                "city":    city,
                "region":  None,
                "country": None,
                "lat":     float(frontend_lat),
                "lon":     float(frontend_lon),
                "source":  "browser_geolocation",
            }

        # ── Case D: Nothing available ──────────────────────────────────────────
        logger.warning(
            "LocationResolver: No usable location source "
            f"(user_location={user_location!r}, has_gps={has_gps})"
        )
        return None

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _geocode_named_location(
        self,
        location: str,
        fallback_lat,
        fallback_lon,
        has_gps: bool,
    ) -> Optional[Dict]:
        """
        Geocode a named city via Open-Meteo. Returns a location dict on success
        or None on failure. Does NOT fall back to GPS — that is handled by the
        caller so the fallback logic stays centralised.
        """
        lat, lon = await self._geocode(location)
        if lat is None or lon is None:
            return None

        logger.info(
            f"LocationResolver: Geocoded '{location}' → ({lat:.5f}, {lon:.5f})"
        )
        return {
            "city":    location,
            "region":  None,
            "country": None,
            "lat":     lat,
            "lon":     lon,
            "source":  "user_input",
        }

    async def _reverse_geocode(self, lat: float, lon: float) -> str:
        """
        Reverse geocode lat/lon to a city name.
        Returns the city name string, or 'Your Location' on failure.
        Failure here does NOT discard the coordinates — they remain usable.
        """
        import os
        api_key = os.getenv("OPENWEATHER_API_KEY")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # 1. OpenWeatherMap Reverse Geocoding (most reliable)
                if api_key:
                    owm_url = (
                        f"http://api.openweathermap.org/geo/1.0/reverse"
                        f"?lat={lat}&lon={lon}&limit=1&appid={api_key}"
                    )
                    try:
                        res = await client.get(owm_url)
                        if res.status_code == 200:
                            data = res.json()
                            if data and len(data) > 0:
                                name = data[0].get("name", "")
                                if name:
                                    return name
                    except Exception as owm_err:
                        logger.warning(f"LocationResolver: OWM reverse geocode failed: {owm_err!r}")

                # 2. Nominatim fallback (rate-limited, but free)
                nominatim_url = (
                    f"https://nominatim.openstreetmap.org/reverse"
                    f"?lat={lat}&lon={lon}&format=json&zoom=10"
                )
                try:
                    res = await client.get(
                        nominatim_url,
                        headers={"User-Agent": "AgriAI/1.0 (hariprasanth5002@gmail.com)"},
                    )
                    if res.status_code == 200:
                        data = res.json()
                        address = data.get("address", {})
                        city = (
                            address.get("city")
                            or address.get("town")
                            or address.get("village")
                            or address.get("county")
                            or ""
                        )
                        if city:
                            return city
                except Exception as nom_err:
                    logger.warning(f"LocationResolver: Nominatim reverse geocode failed: {nom_err!r}")

        except Exception as e:
            logger.error(f"LocationResolver: Reverse geocode outer error: {e!r}")

        # Coordinates are still valid even if we can't name the city
        return "Your Location"

    async def _geocode(self, city: str):
        """
        Free geocoding via Open-Meteo — no API key required.
        Returns (lat, lon) or (None, None).
        """
        try:
            url = "https://geocoding-api.open-meteo.com/v1/search"
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(url, params={"name": city, "count": 1})
                if res.status_code != 200:
                    logger.warning(
                        f"LocationResolver: Geocoding HTTP {res.status_code} for '{city}'"
                    )
                    return None, None
                data = res.json()

            results = data.get("results", [])
            if results:
                r = results[0]
                lat = r.get("latitude")
                lon = r.get("longitude")
                if _is_valid_coords(lat, lon):
                    return float(lat), float(lon)
                logger.warning(
                    f"LocationResolver: Geocoding returned invalid coords for '{city}': {lat}, {lon}"
                )
        except Exception as e:
            logger.error(f"LocationResolver: Geocoding error for '{city}': {e!r}")

        return None, None