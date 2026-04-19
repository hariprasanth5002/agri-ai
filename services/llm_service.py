import os
import asyncio
import httpx
from dotenv import load_dotenv
import time
from collections import deque
from utils.logger import get_logger

load_dotenv()

logger = get_logger("LLMService")


class LLMService:
    """
    Primary  : Google Gemini (gemini-2.0-flash) — free tier
    Fallback : Groq (llama-3.3-70b-versatile)   — free tier
    """

    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.groq_api_key   = os.getenv("GROQ_API_KEY")

        self.gemini_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.0-flash:generateContent"
        )
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"

        # ─── Rate limit tracker ───────────────────────────────────
        self._gemini_times = deque()   # timestamps of recent Gemini calls

    # ─────────────────────────────────────────────────────────────
    # RATE LIMIT GUARD
    # ─────────────────────────────────────────────────────────────
    def _gemini_rate_ok(self) -> bool:
        """
        Returns True if we are safely under the 15 req/min free tier limit.
        Slides a 60-second window over recent call timestamps.
        """
        now = time.time()

        # Drop timestamps older than 60 seconds
        self._gemini_times = deque(
            t for t in self._gemini_times if now - t < 60
        )

        if len(self._gemini_times) >= 14:   # stay under 15/min
            logger.warning("Gemini rate guard: 14 req/min reached → skipping to Groq")
            return False

        self._gemini_times.append(now)
        return True

    # ─────────────────────────────────────────────────────────────
    # PUBLIC METHOD
    # ─────────────────────────────────────────────────────────────
    async def generate(self, prompt: str) -> str:

        # 1️⃣ Try Gemini first (only if rate guard allows)
        if self._gemini_rate_ok():
            response = await self._call_gemini(prompt)
            if response:
                logger.info("Gemini responded successfully")
                return response
        else:
            logger.warning("Rate guard skipped Gemini → going straight to Groq")

        # 2️⃣ Fallback to Groq
        logger.warning("Gemini failed → trying Groq fallback...")
        response = await self._call_groq(prompt)
        if response:
            logger.info("Groq responded successfully")
            return response

        # 3️⃣ Both failed
        logger.error("Both Gemini and Groq failed")
        return "Sorry, the AI service is temporarily unavailable. Please try again."

    # ─────────────────────────────────────────────────────────────
    # GEMINI
    # ─────────────────────────────────────────────────────────────
    async def _call_gemini(self, prompt: str) -> str | None:
        if not self.gemini_api_key:
            logger.error("Gemini: No API key found")
            return None

        payload = {
            "contents": [
                {"parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 1024,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.gemini_url,
                    params={"key": self.gemini_api_key},
                    json=payload,
                )

                logger.info(f"Gemini status: {response.status_code}")

                # ── 429: retry once after 2 s ─────────────────────────
                if response.status_code == 429:
                    logger.warning("Gemini rate limit hit → retrying in 2s...")
                    await asyncio.sleep(2)

                    response = await client.post(
                        self.gemini_url,
                        params={"key": self.gemini_api_key},
                        json=payload,
                    )

                    logger.info(f"Gemini retry status: {response.status_code}")

                    if response.status_code != 200:
                        logger.warning("Gemini retry also failed → falling back to Groq")
                        return None

                # ── Any other non-200 ─────────────────────────────────
                if response.status_code != 200:
                    logger.error(f"Gemini error: {response.text[:200]}")
                    return None

                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()

        except Exception as e:
            logger.error(f"Gemini exception: {e}")
            return None

    # ─────────────────────────────────────────────────────────────
    # GROQ
    # ─────────────────────────────────────────────────────────────
    async def _call_groq(self, prompt: str) -> str | None:
        if not self.groq_api_key:
            logger.error("Groq: No API key found")
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.groq_url,
                    headers={
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.4,
                        "max_tokens": 1024
                    },
                )

                logger.info(f"Groq status: {response.status_code}")

                if response.status_code != 200:
                    logger.error(f"Groq error: {response.text[:200]}")
                    return None

                data = response.json()
                return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logger.error(f"Groq exception: {e}")
            return None