import os
import tempfile
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException
from faster_whisper import WhisperModel
from utils.logger import get_logger

load_dotenv()

logger = get_logger("VoiceService")

app = FastAPI(title="Whisper Voice Service")

# Load model once
model_path = os.getenv("WHISPER_MODEL_PATH", "models/faster-whisper-small01")

try:
    whisper_model = WhisperModel(
        model_path,
        device="cpu",
        compute_type="int8"
    )
    logger.info(f"Whisper model loaded from: {model_path}")
except Exception as e:
    logger.error(f"Failed to load Whisper model: {e}")
    whisper_model = None


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if whisper_model is None:
        raise HTTPException(status_code=503, detail="Whisper model not available")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(await file.read())
            temp_path = tmp.name

        segments, info = whisper_model.transcribe(
            temp_path,
            beam_size=1
        )

        transcript = " ".join([seg.text for seg in segments])

        return {
            "transcript": transcript,
            "language": info.language
        }

    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed. Please try again.")

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)