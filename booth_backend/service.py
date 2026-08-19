"""
Axon Booth backend — proxies the paid/keyed AI calls (ElevenLabs TTS, Groq/
OpenAI Whisper STT, Groq intent classification) so the API keys live on this
server instead of on the kiosk PC.

Camera, microphone capture, local faster-whisper, edge-tts, and Pygame
rendering all stay on the kiosk PC itself — they need physical hardware or
have no key to steal, so there's nothing to gain by proxying them.

Run:
    uvicorn service:booth_api --host 0.0.0.0 --port 8000
"""
import io
import os
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

load_dotenv()

BOOTH_API_KEY = os.environ.get("BOOTH_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
GROQ_STT_MODEL = os.environ.get("AXON_STT_MODEL", "whisper-large-v3-turbo")
GROQ_LLM_MODEL = os.environ.get("AXON_LLM_MODEL", "openai/gpt-oss-120b")
OPENAI_STT_MODEL = os.environ.get("AXON_OPENAI_STT_MODEL", "whisper-1")

booth_api = FastAPI(title="Axon Booth Backend")

openai_client = None
elevenlabs_client = None
groq_client = None

if OPENAI_API_KEY:
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

if ELEVENLABS_API_KEY:
    from elevenlabs.client import ElevenLabs
    elevenlabs_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

if GROQ_API_KEY:
    # Groq exposes an OpenAI-compatible endpoint for both audio
    # transcription and chat completions.
    from openai import OpenAI
    groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")


def _check_auth(x_booth_key: Optional[str]):
    """Shared-secret check so random internet traffic can't burn your
    ElevenLabs/OpenAI/Groq quota. Set BOOTH_API_KEY to enable."""
    if BOOTH_API_KEY and x_booth_key != BOOTH_API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-Booth-Key")


class TTSRequest(BaseModel):
    text: str


class IntentRequest(BaseModel):
    text: str
    options: List[Tuple[str, str]]


@booth_api.get("/health")
def health():
    return {
        "status": "ok",
        "elevenlabs": bool(elevenlabs_client),
        "groq": bool(groq_client),
        "openai": bool(openai_client),
    }


@booth_api.post("/tts")
def tts(req: TTSRequest, x_booth_key: Optional[str] = Header(None)):
    _check_auth(x_booth_key)
    if not elevenlabs_client:
        raise HTTPException(status_code=503, detail="ElevenLabs not configured on backend")
    try:
        audio = elevenlabs_client.text_to_speech.convert(
            voice_id=ELEVENLABS_VOICE_ID,
            model_id=ELEVENLABS_MODEL,
            text=req.text,
        )
        data = b"".join(chunk for chunk in audio)
        return Response(content=data, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ElevenLabs error: {e}")


@booth_api.post("/stt/groq")
async def stt_groq(file: UploadFile = File(...), x_booth_key: Optional[str] = Header(None)):
    _check_auth(x_booth_key)
    if not groq_client:
        raise HTTPException(status_code=503, detail="Groq not configured on backend")
    try:
        data = await file.read()
        buf = io.BytesIO(data)
        buf.name = file.filename or "audio.wav"
        result = groq_client.audio.transcriptions.create(model=GROQ_STT_MODEL, file=buf)
        return {"text": result.text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Groq STT error: {e}")


@booth_api.post("/stt/openai")
async def stt_openai(file: UploadFile = File(...), x_booth_key: Optional[str] = Header(None)):
    _check_auth(x_booth_key)
    if not openai_client:
        raise HTTPException(status_code=503, detail="OpenAI not configured on backend")
    try:
        data = await file.read()
        buf = io.BytesIO(data)
        buf.name = file.filename or "audio.wav"
        result = openai_client.audio.transcriptions.create(model=OPENAI_STT_MODEL, file=buf)
        return {"text": result.text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI STT error: {e}")


@booth_api.post("/classify-intent")
def classify_intent(req: IntentRequest, x_booth_key: Optional[str] = Header(None)):
    _check_auth(x_booth_key)
    if not groq_client:
        raise HTTPException(status_code=503, detail="Groq not configured on backend")

    option_lines = "\n".join(f"- {label}: {desc}" for label, desc in req.options)
    prompt = (
        "You are an intent classifier for a live interactive AI booth. "
        "A visitor just said or typed the following (it may be transcribed "
        "imperfectly, and may be in English, Urdu, Hindi, Arabic, or French):\n"
        f'"{req.text}"\n\n'
        "Pick the single best-matching option below, or reply with exactly "
        "NONE if nothing reasonably matches. Reply with ONLY the option "
        "label and nothing else — no punctuation, no explanation.\n\n"
        f"{option_lines}"
    )
    try:
        resp = groq_client.chat.completions.create(
            model=GROQ_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=150,
            reasoning_effort="low",
        )
        label = resp.choices[0].message.content.strip().strip('"').strip("'").lower()
        valid_labels = {l.lower() for l, _ in req.options}
        return {"label": label if label in valid_labels else None}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Groq intent error: {e}")
