import httpx
import json
from typing import Optional, Dict, Any
from utils.logger import get_logger

from nlp.preprocess import AgriculturalNLPModule
from models.embedding_model import EmbeddingModel

from pipeline.intent_router import IntentRouter
from services.location_resolver import LocationResolver
from services.weather_fetcher import WeatherFetcher
from rag.vector_search import VectorSearchEngine
from pipeline.context_builder import ContextBuilder
from rag.prompt_builder import PromptBuilder
from services.llm_service import LLMService
from pipeline.safety_validator import SafetyValidator

import os

VISION_API_URL = os.getenv("VISION_API_URL", "http://localhost:8000/predict")

logger = get_logger("MultimodalRouter")


class MultimodalRouter:

    def __init__(self):
        self.nlp               = AgriculturalNLPModule()
        self.embedder          = EmbeddingModel()
        self.intent_router     = IntentRouter()
        self.location_resolver = LocationResolver()
        self.weather_fetcher   = WeatherFetcher()
        self.vector_search     = VectorSearchEngine()
        self.context_builder   = ContextBuilder()
        self.prompt_builder    = PromptBuilder()
        self.llm               = LLMService()
        self.safety_validator  = SafetyValidator()

    # ─────────────────────────────────────────────────────────────
    # VISION
    # ─────────────────────────────────────────────────────────────
    async def call_vision_api(self, image_bytes: bytes) -> Dict:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                files    = {"file": ("image.jpg", image_bytes, "image/jpeg")}
                response = await client.post(VISION_API_URL, files=files)
                return response.json()
        except Exception as e:
            logger.error(f"Vision API Error: {e}")
            return {}

    def extract_vision_data(self, vision_output: Dict) -> Optional[Dict]:
        if not vision_output or "predictions" not in vision_output:
            return None
        try:
            is_rejected = vision_output.get("ood_rejected", False)
            data = {
                "confidence_tier":        vision_output.get("confidence_tier", "LOW"),
                "low_confidence_warning": vision_output.get("low_confidence_warning", False),
                "advice":                 vision_output.get("advice", ""),
                "models_agree":           vision_output.get("models_agree", True),
                "warning":                vision_output.get("warning", ""),
                "is_rejected":            is_rejected
            }
            if not is_rejected and len(vision_output["predictions"]) > 0:
                top = vision_output["predictions"][0]
                data["disease"]    = top["class"]
                data["confidence"] = top["confidence"]
            else:
                data["disease"]    = "None"
                data["confidence"] = 0.0
            return data
        except Exception as e:
            logger.error(f"Vision Parse Error: {e}")
            return None

    def _is_valid_prediction(self, vision_data: Optional[Dict]) -> bool:
        """
        Check if the vision prediction is trustworthy enough to use.
        
        We use a LOW hard-rejection threshold (10%) here because:
        - Non-plant images (screenshots, selfies) typically score 5-15%
        - Valid but difficult plant images can score 30-50%
        - The image API's own low_confidence_warning (< 50%) is too aggressive
          for rejection — it's meant as an advisory, not a gate.
        """
        if not vision_data:
            return False
        if vision_data.get("is_rejected", False):
            return False
        confidence = vision_data.get("confidence", 0)
        # Only reject truly garbage predictions (random objects, screenshots)
        if confidence < 0.10:
            return False
        return True

    def _build_unified_text(self, vision_data: Optional[Dict], text: str) -> str:
        if not vision_data:
            return text
        label = vision_data["disease"]
        if "___" in label:
            parts        = label.split("___")
            crop_hint    = parts[0].replace("_", " ").strip()
            disease_hint = parts[1].replace("_", " ").strip()
            prefix       = f"Crop: {crop_hint}. Detected disease: {disease_hint}."
        else:
            disease_hint = label.replace("_", " ").strip()
            prefix       = f"Detected disease: {disease_hint}."
        return f"{prefix} {text}".strip()

    # ─────────────────────────────────────────────────────────────
    # MAIN ROUTING
    # ─────────────────────────────────────────────────────────────
    async def route(
        self,
        text:        Optional[str]   = None,
        voice_text:  Optional[str]   = None,
        image_bytes: Optional[bytes] = None,
        lat:         Optional[float] = None,
        lon:         Optional[float] = None,
    ) -> Dict[str, Any]:

        # 1. Voice → text
        if voice_text:
            text = voice_text

        # 2. Vision
        vision_data = None
        if image_bytes:
            raw         = await self.call_vision_api(image_bytes)
            vision_data = self.extract_vision_data(raw)

            # ── Confidence Gate ──────────────────────────────────────
            # If the vision model is not confident, the image is likely
            # not a valid crop/leaf photo (e.g. a screenshot, selfie, etc.)
            if vision_data and not self._is_valid_prediction(vision_data):
                logger.warning(
                    f"Vision rejected: class={vision_data['disease']}, "
                    f"conf={vision_data['confidence']:.2f}, "
                    f"tier={vision_data['confidence_tier']}"
                )
                # Mark as rejected to pass explicitly to LLM instead of fast-pathing
                vision_data["is_rejected"] = True

        # 3. Unified query
        if vision_data and not vision_data.get("is_rejected"):
            unified_text = self._build_unified_text(vision_data, text or "")
            nlp_disease = vision_data["disease"]
        else:
            unified_text = text or ""
            nlp_disease = None

        # 4. NLP
        nlp_result = self.nlp.process_input(
            text=unified_text,
            disease_prediction=nlp_disease,
        )

        intent = nlp_result["intent"]

        # ─────────────────────────────────────────────────────────
        # FAST PATHS
        # ─────────────────────────────────────────────────────────

        # 🌦️ Weather
        if intent in ("weather_realtime", "weather_forecast"):
            location = await self.location_resolver.resolve(frontend_lat=lat, frontend_lon=lon)

            if not location:
                return {
                    "fast_path": True,
                    "type":      "weather",
                    "error":     "Unable to detect location",
                }

            # ── Fetch current + forecast in a single API request to avoid Open-Meteo limits and ConnectErrors ──
            weather, forecast = await self.weather_fetcher.get_weather_and_forecast(location)

            if not weather:
                return {
                    "fast_path": True,
                    "type":      "weather",
                    "location":  location,
                    "error":     "Weather service unavailable. Please try again.",
                }

            rain_expected = False
            if forecast and forecast.get("forecast"):
                for item in forecast["forecast"]:
                    if item.get("rain_prob", 0) > 0.5:
                        rain_expected = True
                        break

            prompt   = self.prompt_builder.build_weather_prompt(
                weather  = weather,
                forecast = forecast,
                location = location,
                intent   = intent,
                query    = nlp_result["original_text"],
            )
            response = await self.llm.generate(prompt)

            return {
                "fast_path":     True,
                "type":          "weather",
                "intent":        intent,
                "location":      location,
                "current":       weather,
                "forecast":      forecast,
                "rain_expected": rain_expected,
                "response":      response,
            }

        # 👋 Greeting
        if intent == "greeting":
            prompt   = self.prompt_builder.build_greeting_prompt(nlp_result["original_text"])
            response = await self.llm.generate(prompt)
            return {"fast_path": True, "type": "greeting", "response": response}

        # 🚫 Out of scope
        if intent == "out_of_scope":
            prompt   = self.prompt_builder.build_restriction_prompt(nlp_result["original_text"])
            response = await self.llm.generate(prompt)
            return {"fast_path": True, "type": "out_of_scope", "response": response}

        # ─────────────────────────────────────────────────────────
        # NORMAL PIPELINE
        # ─────────────────────────────────────────────────────────

        routing  = self.intent_router.route(intent=intent, has_image=vision_data is not None)
        location = None
        weather  = None

        if routing["needs_location"]:
            location = await self.location_resolver.resolve(frontend_lat=lat, frontend_lon=lon)

        if routing["needs_weather"] and location:
            weather = await self.weather_fetcher.get_weather(location)

        embedding   = self.embedder.generate_embedding(nlp_result["ready_for_embedding"])
        rag_results = []

        if routing["needs_rag"]:
            try:
                rag_results = self.vector_search.search(embedding)
            except Exception as e:
                logger.error(f"RAG Error: {e}")

        final_context = self.context_builder.build(
            nlp      = nlp_result,
            rag      = rag_results,
            vision   = vision_data,
            location = location,
            weather  = weather,
        )

        logger.debug("\n===== FINAL CONTEXT =====")
        logger.debug(json.dumps(final_context, indent=2))
        logger.debug("========================\n")

        prompt   = self.prompt_builder.build(final_context)
        response = await self.llm.generate(prompt)

        safety_result = self.safety_validator.validate(
            response=response, context=final_context
        )

        logger.info(
            f"Safety: safe={safety_result['safe']}, "
            f"issues={len(safety_result['issues'])}"
        )

        return {
            "routing":  routing,
            "context":  final_context,
            "response": safety_result["validated_response"],
            "prompt":   prompt,
            "safety": {
                "safe":   safety_result["safe"],
                "issues": safety_result["issues"],
            },
        }