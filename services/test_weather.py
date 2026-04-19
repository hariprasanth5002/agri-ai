import asyncio
from services.weather_fetcher import WeatherFetcher

async def main():
    weather = WeatherFetcher()
    
    # Mock location
    location = {
        "city": "Chennai",
        "lat": None,
        "lon": None
    }
    
    print("Testing get_weather()....")
    result = await weather.get_weather(location)
    print("Weather Result:", result)
    
    print("\nTesting get_forecast()....")
    forecast = await weather.get_forecast(location)
    print("Forecast Result:", forecast)

if __name__ == "__main__":
    asyncio.run(main())