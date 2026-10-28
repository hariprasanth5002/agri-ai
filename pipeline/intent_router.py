from typing import Dict


class IntentRouter:
    """
    Production-grade Intent Router

    Responsible for:
    - Deciding which external services to call
    - Controlling system cost & latency
    - Enabling dynamic routing logic

    IMPORTANT:
    This class DOES NOT do NLP.
    It only reacts to already detected intent.
    """

    # -----------------------------
    # INTENT GROUPS (REAL-WORLD)
    # -----------------------------
    # -----------------------------
# 🔥 NEW WEATHER INTENTS
# -----------------------------
    DIRECT_WEATHER_INTENTS = {
    "weather_realtime",
    "weather_forecast"
}
    WEATHER_DEPENDENT_INTENTS = {
        "weather_effect",
        "crop_management",            # irrigation, spraying
        "fertilizer_recommendation",  # timing depends on rain
    }

    LOCATION_REQUIRED_INTENTS = {
        "weather_effect",
        "crop_management",
        "fertilizer_recommendation",
    }

    HIGH_PRIORITY_INTENTS = {
        "disease_diagnosis",
        "disease_treatment",
        "disease_severity",
        "prevention",
    }

    LOW_PRIORITY_INTENTS = {
        "general_query"
    }

    # -----------------------------
    # MAIN ROUTING DECISION
    # -----------------------------

    def route(self, intent: str, has_image: bool = False) -> Dict:
        """
        Returns full routing decision in one place.

        This is what your router will use.
        """

        return {
            "intent": intent,

            # What to fetch
            "needs_weather": self.needs_weather(intent),
            "needs_location": self.needs_location(intent),
            "needs_rag": self.needs_rag(intent),

            # Priority handling
            "priority": self.get_priority(intent, has_image),

            # Optimization flags
            "use_fast_response": self.use_fast_path(intent),
            "requires_detailed_answer": self.requires_detailed_answer(intent),
        }

    # -----------------------------
    # SERVICE DECISIONS
    # -----------------------------

    def needs_weather(self, intent: str) -> bool:
        return (
        intent in self.WEATHER_DEPENDENT_INTENTS or
        intent in self.DIRECT_WEATHER_INTENTS
    )

    def needs_location(self, intent: str) -> bool:
        return (
        intent in self.LOCATION_REQUIRED_INTENTS or
        intent in self.DIRECT_WEATHER_INTENTS
    )
    def needs_rag(self, intent: str) -> bool:
    # ❌ Skip RAG for direct weather
        if intent in self.DIRECT_WEATHER_INTENTS:
          return False

    # ❌ Skip RAG for greetings/out_of_scope
        if intent in ["general_query", "greeting", "out_of_scope"]:
          return False

        return True

    # -----------------------------
    # PRIORITY ENGINE
    # -----------------------------

    def get_priority(self, intent: str, has_image: bool) -> str:
        """
        Determines how critical the query is.
        Used later for:
        - LLM prompt weighting
        - Response verbosity
        """

        if has_image and intent in self.HIGH_PRIORITY_INTENTS:
            return "critical"   # disease from image → very important

        if intent in self.HIGH_PRIORITY_INTENTS:
            return "high"

        if intent in self.DIRECT_WEATHER_INTENTS:
           return "low"   # simple info

        if intent in self.WEATHER_DEPENDENT_INTENTS:
           return "medium"

        return "low"

    # -----------------------------
    # OPTIMIZATION LOGIC
    # -----------------------------

    def use_fast_path(self, intent: str) -> bool:
        """
        Skip heavy processing if simple query.
        """
        return intent in self.LOW_PRIORITY_INTENTS

    def requires_detailed_answer(self, intent: str) -> bool:
        """
        Determines if LLM should generate long response.
        """
        return intent in self.HIGH_PRIORITY_INTENTS