"""
tests/test_nlp_preprocess.py

Tests for the NLP preprocessing module, with focus on the location-entity
extraction fix that prevents current-location phrases ("near me", "my area")
from being returned as geocodable city names.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from nlp.preprocess import AgriculturalNLPModule


@pytest.fixture(scope="module")
def nlp():
    return AgriculturalNLPModule()


# ---------------------------------------------------------------------------
# Location entity extraction — current-location phrases must be EXCLUDED
# ---------------------------------------------------------------------------

CURRENT_LOCATION_QUERIES = [
    "what is the weather near me",
    "weather in my area",
    "give me weather for my location",
    "what crops are good here",
    "weather in my area today",
    "weather nearby",
    "current location weather",
    "local weather",
    "temperature around me",
]

@pytest.mark.parametrize("query", CURRENT_LOCATION_QUERIES)
def test_current_location_phrases_not_geocoded(nlp, query):
    """
    Phrases referring to the user's GPS location must NOT appear in
    entities['location'], because they cannot be geocoded as city names.
    """
    result = nlp.process_input(query)
    locations = result["entities"].get("location", [])
    # None of the current-location keywords should appear
    bad_phrases = {
        "near me", "my area", "my location", "here", "nearby",
        "current location", "weather in my area", "local weather",
        "around me", "my place", "my region", "my field", "this area",
    }
    for loc in locations:
        assert loc not in bad_phrases, (
            f"Query '{query}' produced bad location entity '{loc}'. "
            f"Current-location phrases must not be geocoded."
        )


# ---------------------------------------------------------------------------
# Location entity extraction — explicit city names SHOULD be captured
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query,expected_city", [
    ("what is the weather in coimbatore", "coimbatore"),
    ("weather in Chennai today", "chennai"),
    ("farming tips for maharashtra", "maharashtra"),
    ("best crops for punjab region", "punjab"),
])
def test_explicit_city_extracted(nlp, query, expected_city):
    """Explicit city names in queries should still be extracted."""
    result = nlp.process_input(query.lower())
    locations = result["entities"].get("location", [])
    assert len(locations) > 0, (
        f"Query '{query}' should have produced a location entity, got none."
    )


# ---------------------------------------------------------------------------
# Intent detection — weather intents
# ---------------------------------------------------------------------------

def test_weather_realtime_intent(nlp):
    result = nlp.process_input("weather today")
    assert result["intent"] == "weather_realtime"

def test_weather_forecast_intent_rain(nlp):
    result = nlp.process_input("will it rain today")
    assert result["intent"] == "weather_forecast"

def test_weather_forecast_intent_tomorrow(nlp):
    result = nlp.process_input("weather tomorrow")
    assert result["intent"] == "weather_forecast"

def test_greeting_intent(nlp):
    result = nlp.process_input("hello")
    assert result["intent"] == "greeting"

def test_out_of_scope_intent(nlp):
    result = nlp.process_input("recommend me a movie")
    assert result["intent"] == "out_of_scope"

def test_disease_treatment_intent(nlp):
    result = nlp.process_input("how to treat powdery mildew on tomato")
    assert result["intent"] in ("disease_treatment", "disease_diagnosis")
