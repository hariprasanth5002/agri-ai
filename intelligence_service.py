import os
import time
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
import httpx
from pipeline.multimodal_router import MultimodalRouter
from services.weather_fetcher import WeatherFetcher
from utils.logger import get_logger

logger = get_logger("IntelligenceService")

app = FastAPI(
    title="Multimodal Agricultural Intelligence API",
    description="Agri AI backend — weather, crop advice, disease diagnosis.",
    version="1.0.0",
)

# ---------------------------
# CONFIGURATION
# ---------------------------
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10")) * 1024 * 1024  # bytes
VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_URL", "http://127.0.0.1:8002/transcribe")

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
ALLOWED_VOICE_TYPES = {"audio/wav", "audio/mpeg", "audio/ogg", "audio/webm", "audio/x-wav"}

# ---------------------------
# CORS MIDDLEWARE
# ---------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# ROOT ENDPOINT
# ---------------------------
@app.get("/")
async def read_index():
    return {"status": "Agri AI API is running! Frontend is hosted separately."}


# ---------------------------
# HEALTH CHECK  (BUG 7 FIX)
# render.yaml declares healthCheckPath: /health
# Without this endpoint Render marks the service unhealthy.
# ---------------------------
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "agri-ai-backend"}


# ---------------------------
# WEATHER DIAGNOSTIC
# Read-only endpoint for debugging weather providers without needing
# Render log access. Returns which provider succeeded or failed.
# Usage: GET /weather/diagnostic?lat=11.0&lon=77.0
# ---------------------------
@app.get("/weather/diagnostic")
async def weather_diagnostic(
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lon: Optional[float] = Query(None, ge=-180, le=180),
    city: Optional[str] = Query(None, max_length=100),
):
    """
    Diagnostic-only endpoint. Does NOT affect normal request flow.
    Returns structured provider status for debugging.
    """
    from services.weather_fetcher import WeatherFetcher as _WF
    wf = _WF()

    location: dict = {}
    if lat is not None and lon is not None:
        location = {"lat": lat, "lon": lon, "city": city or ""}
    elif city:
        location = {"city": city, "lat": None, "lon": None}
    else:
        return {"error": "Provide lat+lon or city query parameter.", "code": "MISSING_PARAMS"}

    start = time.time()
    try:
        current, forecast = await wf.get_weather_and_forecast(location)
        elapsed = round(time.time() - start, 2)
        if current:
            return {
                "ok": True,
                "source": current.get("source"),
                "condition": current.get("condition"),
                "temperature_c": current.get("temperature"),
                "location_used": location,
                "elapsed_s": elapsed,
            }
        return {
            "ok": False,
            "code": "WEATHER_ALL_PROVIDERS_FAILED",
            "location_used": location,
            "elapsed_s": elapsed,
        }
    except Exception as e:
        return {
            "ok": False,
            "code": "DIAGNOSTIC_ERROR",
            "detail": str(e)[:200],
            "elapsed_s": round(time.time() - start, 2),
        }


router = MultimodalRouter()


# ---------------------------
# VALIDATION HELPERS
# ---------------------------
async def validate_upload(file: UploadFile, allowed_types: set, label: str) -> bytes:
    """Validate file type and size, return bytes."""
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} file type: {file.content_type}. Allowed: {', '.join(allowed_types)}"
        )

    content = await file.read()

    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"{label.capitalize()} file too large. Max: {MAX_UPLOAD_SIZE // (1024*1024)}MB"
        )

    return content


# ---------------------------
# TEXT ONLY
# ---------------------------
@app.post("/text")
async def text_query(
    text: str = Form(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None)
):
    # Validate coords if provided
    import math
    if lat is not None and lon is not None:
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            logger.warning(f"Text endpoint: invalid coords lat={lat} lon={lon} — ignoring")
            lat, lon = None, None

    logger.debug(
        f"Text endpoint: text_len={len(text)}, "
        f"has_coords={lat is not None and lon is not None}"
    )
    try:
        result = await router.route(text=text, lat=lat, lon=lon)
        return result
    except Exception as e:
        logger.error(f"Text query error [{type(e).__name__}]: {e!r}")
        raise HTTPException(status_code=500, detail="Internal server error. Please try again.")


# ---------------------------
# VOICE FILE (CALLS VOICE MICROSERVICE)
# ---------------------------
@app.post("/voice")
async def voice_query(
    file: UploadFile = File(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None)
):
    try:
        content = await validate_upload(file, ALLOWED_VOICE_TYPES, "voice")

        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {
                "file": (file.filename, content, file.content_type)
            }
            response = await client.post(VOICE_SERVICE_URL, files=files)
            voice_result = response.json()

        transcript = voice_result.get("transcript")
        result = await router.route(voice_text=transcript, lat=lat, lon=lon)

        result["transcript"] = transcript
        result["detected_language"] = voice_result.get("language")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Voice query error: {e}")
        raise HTTPException(status_code=500, detail="Voice processing failed. Please try again.")


# ---------------------------
# IMAGE ONLY
# ---------------------------
@app.post("/image")
async def image_query(
    file: UploadFile = File(...),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None)
):
    try:
        image_bytes = await validate_upload(file, ALLOWED_IMAGE_TYPES, "image")
        result = await router.route(image_bytes=image_bytes, lat=lat, lon=lon)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image query error: {e}")
        raise HTTPException(status_code=500, detail="Image processing failed. Please try again.")


# ---------------------------
# TTS PROXY STREAM
# ---------------------------
from fastapi.responses import StreamingResponse
import urllib.parse

@app.get("/tts")
async def tts_proxy(text: str, lang: str = "en"):
    """
    A dedicated backend proxy route to stream TTS audio and bypass all frontend CORS/CAPTCHA browser blocks.
    It calls Google's translation API securely server-to-server and streams the accurate MP3 bytes to the client.
    """
    try:
        # Use gtx client which works well from server-side IPs without restrictions
        # Limit text chunk to ~200 chars to respect the free API limits
        chunk = text[:190]
        url = f"https://translate.googleapis.com/translate_tts?ie=UTF-8&tl={lang}&client=gtx&q={urllib.parse.quote(chunk)}"
        
        async def generate_audio():
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        logger.error(f"TTS Proxy Upstream Error: {response.status_code}")
                        # Return empty if upstream fails
                        yield b""
                        return
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        yield chunk
                        
        return StreamingResponse(generate_audio(), media_type="audio/mpeg")
    except Exception as e:
        logger.error(f"TTS Proxy Error: {e}")
        raise HTTPException(status_code=500, detail="Voice stream failed.")

# ---------------------------
# FULL MULTIMODAL
# ---------------------------
@app.post("/multimodal")
async def multimodal_query(
    text: Optional[str] = Form(None),
    voice: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None)
):
    try:
        voice_text = None
        image_bytes = None

        # If voice provided → validate + call voice service
        if voice:
            voice_content = await validate_upload(voice, ALLOWED_VOICE_TYPES, "voice")

            async with httpx.AsyncClient(timeout=60.0) as client:
                files = {
                    "file": (voice.filename, voice_content, voice.content_type)
                }
                response = await client.post(VOICE_SERVICE_URL, files=files)
                voice_result = response.json()

            voice_text = voice_result.get("transcript")

        # If image provided → validate
        if image:
            image_bytes = await validate_upload(image, ALLOWED_IMAGE_TYPES, "image")

        result = await router.route(
            text=text,
            voice_text=voice_text,
            image_bytes=image_bytes,
            lat=lat,
            lon=lon
        )

        result["voice_transcript"] = voice_text

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Multimodal query error: {e}")
        raise HTTPException(status_code=500, detail="Processing failed. Please try again.")