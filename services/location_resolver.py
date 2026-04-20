import httpx
from typing import Optional, Dict
from utils.logger import get_logger

logger = get_logger("LocationResolver")


class LocationResolver:
    """
    Resolves user location using (in priority order):
    1. Frontend browser geolocation (lat/lon from navigator.geolocation)
    2. User-provided city name (geocoded via Open-Meteo)

    NOTE: IP-based geolocation was removed because it resolves the
    *server's* location in deployment, not the user's actual location.
    The frontend now sends browser GPS coordinates with every request.
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
            user_location: City name typed by the user in the query
            frontend_lat:  Latitude from browser geolocation API
            frontend_lon:  Longitude from browser geolocation API
        """

        # Priority 1: Frontend browser geolocation (most accurate)
        if frontend_lat is not None and frontend_lon is not None:
            city = await self._reverse_geocode(frontend_lat, frontend_lon)
            logger.info(f"LocationResolver: Using browser geolocation → {city} ({frontend_lat}, {frontend_lon})")
            return {
                "city":    city,
                "region":  None,
                "country": None,
                "lat":     frontend_lat,
                "lon":     frontend_lon,
                "source":  "browser_geolocation",
            }

        # Priority 2: User-provided city name (geocode to get lat/lon)
        if user_location:
            return await self._parse_user_location(user_location)

        # No location available
        logger.warning("LocationResolver: No location source available")
        return None

    async def _parse_user_location(self, location: str) -> Dict:
        """
        Parse user-provided location string.
        Tries to geocode it via Open-Meteo for lat/lon.
        """
        lat, lon = await self._geocode(location)
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
        Reverse geocode lat/lon to get a city name.
        Returns city name or 'Your Location' as fallback.
        """
        import os
        api_key = os.getenv("OPENWEATHER_API_KEY")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # 1. Try OpenWeatherMap Reverse Geocoding (Most Reliable)
                if api_key:
                    owm_url = f"http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={lon}&limit=1&appid={api_key}"
                    res = await client.get(owm_url)
                    if res.status_code == 200:
                        data = res.json()
                        if data and len(data) > 0:
                            return data[0].get("name", "Your Location")

                # 2. Try Nominatim (Strict rate limits, easily returns HTML 403)
                nominatim_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=10"
                res = await client.get(
                    nominatim_url,
                    headers={"User-Agent": "AgriAI/1.0 (hariprasanth5002@gmail.com)"}
                )
                if res.status_code == 200:
                    data = res.json()
                    address = data.get("address", {})
                    city = (
                        address.get("city")
                        or address.get("town")
                        or address.get("village")
                        or address.get("county")
                        or "Your Location"
                    )
                    return city
                
                return "Your Location"
        except Exception as e:
            logger.error(f"Reverse geocode error: {repr(e)}")
            return "Your Location"

    async def _geocode(self, city: str):
        """
        Free geocoding via Open-Meteo - no API key required.
        Returns (lat, lon) or (None, None).
        """
        try:
            url = "https://geocoding-api.open-meteo.com/v1/search"
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url, params={"name": city, "count": 1})
                data = res.json()

            results = data.get("results", [])
            if results:
                r = results[0]
                return r["latitude"], r["longitude"]
        except Exception as e:
            logger.error(f"Geocoding error for '{city}': {repr(e)}")

        return None, None