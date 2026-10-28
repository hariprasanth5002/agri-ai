import math
import os
from typing import Optional, Dict, List, Tuple
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

logger = get_logger("WeatherFetcher")

WMO_CONDITION = {
    0: "Clear sky",       1: "Mainly clear",    2: "Partly cloudy",  3: "Overcast",
    45: "Foggy",          48: "Icy fog",
    51: "Light drizzle",  53: "Drizzle",        55: "Heavy drizzle",
    61: "Light rain",     63: "Rain",            65: "Heavy rain",
    71: "Light snow",     73: "Snow",            75: "Heavy snow",
    80: "Rain showers",   81: "Heavy showers",   82: "Violent showers",
    95: "Thunderstorm",   96: "Thunderstorm + hail", 99: "Thunderstorm + hail",
}

WMO_ICON = {
    0: "clear",  1: "mainly_clear",  2: "partly_cloudy",  3: "overcast",
    45: "fog",   48: "fog",
    51: "drizzle", 53: "drizzle", 55: "drizzle",
    61: "rain",  63: "rain",  65: "rain",
    71: "snow",  73: "snow",  75: "snow",
    80: "showers", 81: "showers", 82: "showers",
    95: "thunderstorm", 96: "thunderstorm", 99: "thunderstorm",
}


def _is_valid_coords(lat, lon) -> bool:
    """Validate that lat/lon are finite numbers within legal ranges."""
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(lat) and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    )


class WeatherFetcher:
    """
    Weather data via a free, key-free provider chain:
      Tier 1 — Open-Meteo  (free, no API key)
      Tier 2 — OpenWeatherMap (free tier, requires OPENWEATHER_API_KEY env var)
      Tier 3 — Failure  (returns None, None — never returns fabricated data)

    IMPORTANT: Mock data is NO LONGER returned. When all providers fail,
    (None, None) is returned so the caller can communicate the failure
    honestly to the user rather than showing fabricated weather values.
    """

    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    # ------------------------------------------------------------------
    # ASYNC COORD RESOLUTION  (BUG 2 / BUG 4 FIX)
    # Previously this was a synchronous method that called
    # asyncio.get_event_loop().run_until_complete() — a fatal anti-pattern
    # inside a running async event loop (FastAPI / uvicorn). It raised
    # "RuntimeError: This event loop is already running" every time a
    # city name (rather than lat/lon) was passed.
    # ------------------------------------------------------------------
    async def _get_coords(self, location: Dict) -> Tuple[Optional[float], Optional[float]]:
        """
        Extract and validate lat/lon from a location dict.
        Falls back to geocoding the city name if coordinates are absent.
        Fully async — safe to await inside FastAPI handlers.
        """
        lat = location.get("lat")
        lon = location.get("lon")

        if lat is not None and lon is not None and _is_valid_coords(lat, lon):
            return float(lat), float(lon)

        city = location.get("city")
        if city:
            lat, lon = await self._geocode_city(city)
            if lat is not None and lon is not None and _is_valid_coords(lat, lon):
                return float(lat), float(lon)
            logger.warning(
                f"WeatherFetcher: Could not geocode city '{city}'. "
                "Returning (None, None)."
            )

        return None, None

    # ------------------------------------------------------------------
    # PRIMARY: Open-Meteo — combined current + forecast
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((
            httpx.ConnectError, httpx.TimeoutException,
            httpx.NetworkError, httpx.HTTPStatusError,
        )),
        reraise=True,
    )
    async def get_weather_and_forecast(
        self, location: Dict
    ) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        Fetch current weather + 10-day forecast in a single Open-Meteo call.
        Falls back to OpenWeatherMap if Open-Meteo fails.
        Returns (None, None) when all providers fail — never returns mock data.
        """
        if not location:
            logger.warning("WeatherFetcher.get_weather_and_forecast: location is None/empty")
            return None, None

        lat, lon = await self._get_coords(location)
        if lat is None or lon is None:
            logger.warning(
                f"WeatherFetcher: No valid coords for location {location!r}. "
                "Skipping weather fetch."
            )
            return None, None

        try:
            query = (
                f"latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
                f"weather_code,wind_speed_10m,precipitation,surface_pressure"
                f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                f"precipitation_probability_max,wind_speed_10m_max"
                f"&hourly=precipitation_probability,temperature_2m,weather_code"
                f"&timezone=auto&forecast_days=10"
            )
            url = f"{self.BASE_URL}?{query}"

            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(url)

                if res.status_code >= 500:
                    logger.warning(
                        f"WeatherFetcher [WEATHER_PROVIDER_HTTP_ERROR]: "
                        f"Open-Meteo HTTP {res.status_code}"
                    )
                    res.raise_for_status()

                if res.status_code != 200:
                    logger.warning(
                        f"WeatherFetcher [WEATHER_PROVIDER_HTTP_ERROR]: "
                        f"Open-Meteo returned {res.status_code}: {res.text[:200]}"
                    )
                    res.raise_for_status()

                try:
                    data = res.json()
                except Exception as json_err:
                    logger.error(
                        f"WeatherFetcher [WEATHER_PROVIDER_INVALID_RESPONSE]: "
                        f"JSON parse error: {json_err}. Raw: {res.text[:200]}"
                    )
                    return None, None

            current = self._parse_current(data, location)
            forecast = self._parse_forecast(data, location)

            if not self._validate_current(current):
                logger.error(
                    "WeatherFetcher [WEATHER_PROVIDER_INVALID_RESPONSE]: "
                    "Open-Meteo returned unparseable current weather."
                )
                return None, None

            logger.info(
                f"WeatherFetcher: Open-Meteo success for "
                f"({lat:.4f}, {lon:.4f}) — {current.get('condition')}"
            )
            return current, forecast

        except Exception as e:
            logger.error(
                f"WeatherFetcher [WEATHER_PROVIDER_HTTP_ERROR]: "
                f"Open-Meteo failed: {e!r}. Trying OWM fallback…"
            )
            try:
                return await self._get_owm_fallback(location, lat, lon)
            except Exception as owm_e:
                logger.error(
                    f"WeatherFetcher [WEATHER_ALL_PROVIDERS_FAILED]: "
                    f"OWM fallback also failed: {owm_e!r}. Returning (None, None)."
                )
                # BUG 5 FIX: Return (None, None) instead of mock data.
                # The router will communicate the failure honestly to the user.
                return None, None

    # ------------------------------------------------------------------
    # Individual get_weather (backwards-compat)
    # ------------------------------------------------------------------
    async def get_weather(self, location: Dict) -> Optional[Dict]:
        """Returns current weather for a location. Returns None on failure."""
        if not location:
            return None

        lat, lon = await self._get_coords(location)
        if lat is None or lon is None:
            logger.warning(f"WeatherFetcher.get_weather: No valid coords for {location!r}")
            return None

        try:
            query = (
                f"latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
                f"weather_code,wind_speed_10m,precipitation,surface_pressure"
                f"&timezone=auto"
            )
            url = f"{self.BASE_URL}?{query}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)

                if res.status_code >= 500:
                    res.raise_for_status()

                if res.status_code != 200:
                    logger.warning(
                        f"WeatherFetcher.get_weather [WEATHER_PROVIDER_HTTP_ERROR]: "
                        f"HTTP {res.status_code}: {res.text[:200]}"
                    )
                    res.raise_for_status()

                try:
                    data = res.json()
                except Exception as json_err:
                    logger.error(
                        f"WeatherFetcher.get_weather [WEATHER_PROVIDER_INVALID_RESPONSE]: "
                        f"JSON error: {json_err}"
                    )
                    return None

            return self._parse_current(data, location)

        except Exception as e:
            logger.error(f"WeatherFetcher.get_weather error: {e!r}")
            return None

    # ------------------------------------------------------------------
    # Individual get_forecast (backwards-compat)
    # ------------------------------------------------------------------
    async def get_forecast(self, location: Dict) -> Optional[Dict]:
        """Returns 10-day daily forecast + hourly precipitation. None on failure."""
        if not location:
            return None

        lat, lon = await self._get_coords(location)
        if lat is None or lon is None:
            return None

        try:
            query = (
                f"latitude={lat}&longitude={lon}"
                f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                f"precipitation_probability_max,wind_speed_10m_max"
                f"&hourly=precipitation_probability,temperature_2m,weather_code"
                f"&timezone=auto&forecast_days=10"
            )
            url = f"{self.BASE_URL}?{query}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)

                if res.status_code >= 500:
                    res.raise_for_status()

                if res.status_code != 200:
                    logger.warning(
                        f"WeatherFetcher.get_forecast [WEATHER_PROVIDER_HTTP_ERROR]: "
                        f"HTTP {res.status_code}: {res.text[:200]}"
                    )
                    res.raise_for_status()

                try:
                    data = res.json()
                except Exception as json_err:
                    logger.error(
                        f"WeatherFetcher.get_forecast [WEATHER_PROVIDER_INVALID_RESPONSE]: "
                        f"JSON error: {json_err}"
                    )
                    return None

            return self._parse_forecast(data, location)

        except Exception as e:
            logger.error(f"WeatherFetcher.get_forecast error: {e!r}")
            return None

    # ------------------------------------------------------------------
    # COORD RESOLUTION (async)
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
            httpx.ConnectError, httpx.TimeoutException,
            httpx.NetworkError, httpx.HTTPStatusError,
        )),
        reraise=True,
    )
    async def _geocode_city(self, city: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Use Open-Meteo geocoding API to convert city name → lat/lon.
        No API key required. Fully async.
        """
        try:
            url = "https://geocoding-api.open-meteo.com/v1/search"
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(url, params={"name": city, "count": 1})

                if res.status_code >= 500:
                    res.raise_for_status()

                if res.status_code != 200:
                    logger.warning(
                        f"WeatherFetcher: Geocoding HTTP {res.status_code} for '{city}'"
                    )
                    return None, None

                try:
                    data = res.json()
                except Exception as json_err:
                    logger.error(
                        f"WeatherFetcher: Geocoding JSON error for '{city}': {json_err}"
                    )
                    return None, None

            results = data.get("results", [])
            if results:
                r = results[0]
                lat = r.get("latitude")
                lon = r.get("longitude")
                if _is_valid_coords(lat, lon):
                    return float(lat), float(lon)
                logger.warning(
                    f"WeatherFetcher: Geocoding returned invalid coords for '{city}': {lat}, {lon}"
                )

        except Exception as e:
            logger.error(f"WeatherFetcher: Geocoding error for '{city}': {e!r}")

        return None, None

    # ------------------------------------------------------------------
    # PARSERS
    # ------------------------------------------------------------------
    def _parse_current(self, data: Dict, location: Dict) -> Dict:
        cur  = data.get("current", {})
        code = cur.get("weather_code", 0)

        return {
            "temperature":   round(cur.get("temperature_2m", 0), 1),
            "feels_like":    round(cur.get("apparent_temperature", 0), 1),
            "humidity":      cur.get("relative_humidity_2m", 0),
            "pressure":      round(cur.get("surface_pressure", 0), 1),
            "precipitation": cur.get("precipitation", 0),
            "wind_speed":    round(cur.get("wind_speed_10m", 0), 1),
            "condition":     WMO_CONDITION.get(code, "Unknown"),
            "icon":          WMO_ICON.get(code, "clear"),
            "weather_code":  code,
            "location_name": location.get("city", ""),
            "country":       location.get("country", ""),
            "source":        "open-meteo",
        }

    def _validate_current(self, current: Optional[Dict]) -> bool:
        """Basic sanity check — ensure we got a real dict with a temperature."""
        if not current or not isinstance(current, dict):
            return False
        temp = current.get("temperature")
        return temp is not None and math.isfinite(float(temp))

    def _parse_forecast(self, data: Dict, location: Dict) -> Dict:
        daily  = data.get("daily", {})
        hourly = data.get("hourly", {})

        dates       = daily.get("time", [])
        codes       = daily.get("weather_code", [])
        temp_max    = daily.get("temperature_2m_max", [])
        temp_min    = daily.get("temperature_2m_min", [])
        precip_prob = daily.get("precipitation_probability_max", [])
        wind_max    = daily.get("wind_speed_10m_max", [])

        hourly_times  = hourly.get("time", [])
        hourly_precip = hourly.get("precipitation_probability", [])
        hourly_temp   = hourly.get("temperature_2m", [])
        hourly_codes  = hourly.get("weather_code", [])

        forecast_list = []
        for i, date_str in enumerate(dates):
            code = codes[i] if i < len(codes) else 0
            forecast_list.append({
                "date":         date_str,
                "day_label":    self._day_label(date_str, i),
                "condition":    WMO_CONDITION.get(code, "Unknown"),
                "icon":         WMO_ICON.get(code, "clear"),
                "weather_code": code,
                "temp_max":     round(temp_max[i], 1) if i < len(temp_max) else None,
                "temp_min":     round(temp_min[i], 1) if i < len(temp_min) else None,
                "rain_prob":    (precip_prob[i] / 100) if i < len(precip_prob) else 0,
                "wind_max":     round(wind_max[i], 1) if i < len(wind_max) else None,
            })

        hourly_by_date = self._extract_all_hourly(
            hourly_times, hourly_precip, hourly_temp, hourly_codes
        )

        return {
            "city":           location.get("city", ""),
            "forecast":       forecast_list,
            "hourly_by_date": hourly_by_date,
            "source":         "open-meteo",
        }

    def _day_label(self, date_str: str, index: int) -> str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if index == 0:
                return "Today"
            if index == 1:
                return "Tmrw"
            return dt.strftime("%a")
        except Exception:
            return date_str

    def _extract_all_hourly(
        self,
        times: List[str],
        precip: List[float],
        temp: List[float],
        codes: List[int],
    ) -> Dict[str, List[Dict]]:
        """Extract 8 evenly-spaced hourly slots (every 3 h) for each forecast day."""
        hourly_by_date: Dict[str, List[Dict]] = {}

        for i, t in enumerate(times):
            date_str = t[:10]
            hour = int(t[11:13])

            if hour % 3 == 0:
                dt = datetime.strptime(t, "%Y-%m-%dT%H:%M")
                hour_12 = dt.hour % 12 or 12
                ampm = "am" if dt.hour < 12 else "pm"
                time_label = f"{hour_12}{ampm}"

                if date_str not in hourly_by_date:
                    hourly_by_date[date_str] = []

                if len(hourly_by_date[date_str]) < 8:
                    prob = precip[i] if i < len(precip) else 0
                    code = codes[i] if i < len(codes) else 0

                    # Correct Open-Meteo contradiction (condition is rain but prob is 0)
                    if code >= 51 and prob < 20:
                        prob = 60 if code < 80 else 85
                        if code >= 95:
                            prob = 90

                    hourly_by_date[date_str].append({
                        "time":        time_label,
                        "precip_prob": prob,
                        "temperature": round(temp[i], 1) if i < len(temp) else None,
                    })

        return hourly_by_date

    # ------------------------------------------------------------------
    # FALLBACK TIER 2: OpenWeatherMap
    # ------------------------------------------------------------------
    async def _get_owm_fallback(
        self, location: Dict, lat: float, lon: float
    ) -> Tuple[Optional[Dict], Optional[Dict]]:
        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENWEATHER_API_KEY is not set — OWM fallback unavailable."
            )

        async with httpx.AsyncClient(timeout=12.0) as client:
            # Current weather
            curr_url = (
                f"https://api.openweathermap.org/data/2.5/weather"
                f"?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            )
            res_curr = await client.get(curr_url)
            res_curr.raise_for_status()
            curr_data = res_curr.json()

            # Forecast (5 day / 3 h)
            fc_url = (
                f"https://api.openweathermap.org/data/2.5/forecast"
                f"?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            )
            res_fc = await client.get(fc_url)
            res_fc.raise_for_status()
            fc_data = res_fc.json()

        current  = self._parse_owm_current(curr_data, location)
        forecast = self._parse_owm_forecast(fc_data, location)

        logger.info(
            f"WeatherFetcher: OWM fallback success for ({lat:.4f}, {lon:.4f}) "
            f"— {current.get('condition')}"
        )
        return current, forecast

    def _parse_owm_current(self, data: Dict, location: Dict) -> Dict:
        main       = data.get("main", {})
        wind       = data.get("wind", {})
        rain       = data.get("rain", {})
        weather    = data.get("weather", [{}])[0]
        desc       = weather.get("description", "Unknown").capitalize()

        icon = "partly_cloudy"
        desc_lower = desc.lower()
        if "clear" in desc_lower:
            icon = "clear"
        elif "rain" in desc_lower or "drizzle" in desc_lower:
            icon = "rain"
        elif "storm" in desc_lower or "thunder" in desc_lower:
            icon = "thunderstorm"
        elif "snow" in desc_lower:
            icon = "snow"
        elif "fog" in desc_lower or "mist" in desc_lower:
            icon = "fog"

        return {
            "temperature":   round(main.get("temp", 0), 1),
            "feels_like":    round(main.get("feels_like", 0), 1),
            "humidity":      main.get("humidity", 0),
            "pressure":      main.get("pressure", 0),
            "precipitation": rain.get("1h", 0),
            "wind_speed":    round(wind.get("speed", 0) * 3.6, 1),  # m/s → km/h
            "condition":     desc,
            "icon":          icon,
            "weather_code":  1,
            "location_name": location.get("city", "Local Area"),
            "country":       location.get("country", ""),
            "source":        "openweathermap",
        }

    def _parse_owm_forecast(self, data: Dict, location: Dict) -> Dict:
        items = data.get("list", [])
        daily_data: Dict[str, Dict] = {}

        for item in items:
            date_str = item.get("dt_txt", "")[:10]
            if not date_str:
                continue
            temp = item.get("main", {}).get("temp", 0)
            pop  = item.get("pop", 0) * 100  # OWM gives 0–1
            if date_str not in daily_data:
                daily_data[date_str] = {
                    "temps": [],
                    "pop":   [],
                    "weather": item.get("weather", [{}])[0].get("description", "Unknown").capitalize(),
                }
            daily_data[date_str]["temps"].append(temp)
            daily_data[date_str]["pop"].append(pop)

        forecast_list = []
        for i, (date_str, info) in enumerate(list(daily_data.items())[:10]):
            forecast_list.append({
                "date":         date_str,
                "day_label":    self._day_label(date_str, i),
                "condition":    info["weather"],
                "icon":         "partly_cloudy",
                "weather_code": 1,
                "temp_max":     round(max(info["temps"]), 1),
                "temp_min":     round(min(info["temps"]), 1),
                "rain_prob":    round(max(info["pop"]) / 100, 2),
                "wind_max":     0.0,
            })

        # Build minimal hourly_by_date from the OWM 3-h data (no mock values)
        hourly_by_date: Dict[str, List[Dict]] = {}
        for item in items:
            dt_txt   = item.get("dt_txt", "")
            date_str = dt_txt[:10]
            time_str = dt_txt[11:16]
            if not date_str or not time_str:
                continue
            try:
                dt = datetime.strptime(time_str, "%H:%M")
                hour_12 = dt.hour % 12 or 12
                ampm = "am" if dt.hour < 12 else "pm"
                time_label = f"{hour_12}{ampm}"
            except Exception:
                time_label = time_str

            if date_str not in hourly_by_date:
                hourly_by_date[date_str] = []
            if len(hourly_by_date[date_str]) < 8:
                hourly_by_date[date_str].append({
                    "time":        time_label,
                    "precip_prob": round(item.get("pop", 0) * 100, 1),
                    "temperature": round(item.get("main", {}).get("temp", 0), 1),
                })

        return {
            "city":           location.get("city", "Local Area"),
            "forecast":       forecast_list,
            "hourly_by_date": hourly_by_date,
            "source":         "openweathermap",
        }