"""OpenRouter-backed text-to-speech for Practice question playback."""
from __future__ import annotations

import os
import io
from dataclasses import dataclass
from fractions import Fraction

import requests
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

import config as app_config
from storage import user_settings


MAX_TTS_CHARS = 5_000
_ROUTES_REGISTERED = False

@dataclass(frozen=True)
class TTSCapability:
    """The small provider-specific surface used by Practice playback."""

    voices: tuple[str, ...]
    response_format: str = "mp3"
    pcm_sample_rate: int | None = None


# Voice IDs come from OpenRouter's speech-model metadata. The second voice is a
# same-model fallback for an upstream voice-specific validation failure.
TTS_CAPABILITIES = {
    "google/gemini-3.1-flash-tts-preview": TTSCapability(
        ("Kore", "Puck"), response_format="pcm", pcm_sample_rate=24_000,
    ),
    "x-ai/grok-voice-tts-1.0": TTSCapability(("eve", "ara")),
    "deepgram/flux-tts:free": TTSCapability(("flux-kit-en", "flux-alexis-en")),
}


def _base_url() -> str:
    return (
        (os.environ.get("OPENROUTER_BASE_URL") or "").strip()
        or app_config.OPENROUTER_BASE_URL_DEFAULT
    ).rstrip("/")


def _pcm_to_mp3(payload: bytes, sample_rate: int) -> bytes:
    """Encode signed 16-bit mono PCM as an MP3 entirely in memory."""
    try:
        import av
    except ImportError as exc:
        raise RuntimeError("Practice TTS needs the 'av' package to play PCM audio.") from exc
    if not payload or len(payload) % 2:
        raise RuntimeError("The TTS provider returned invalid PCM audio.")

    target = io.BytesIO()
    try:
        container = av.open(target, mode="w", format="mp3")
        stream = container.add_stream("libmp3lame", rate=sample_rate)
        stream.layout = "mono"
        bytes_per_second = sample_rate * 2
        sample_offset = 0
        for offset in range(0, len(payload), bytes_per_second):
            chunk = payload[offset:offset + bytes_per_second]
            frame = av.AudioFrame(format="s16", layout="mono", samples=len(chunk) // 2)
            frame.planes[0].update(chunk)
            frame.sample_rate = sample_rate
            frame.pts = sample_offset
            frame.time_base = Fraction(1, sample_rate)
            sample_offset += frame.samples
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
        container.close()
    except Exception as exc:
        raise RuntimeError(f"Could not convert provider PCM audio to MP3: {exc}") from exc
    encoded = target.getvalue()
    if not encoded:
        raise RuntimeError("PCM-to-MP3 conversion returned empty audio.")
    return encoded


def _is_mp3(payload: bytes) -> bool:
    """Recognize an ID3 header or an MPEG audio frame sync word."""
    return (
        payload.startswith(b"ID3")
        or (len(payload) >= 2 and payload[0] == 0xFF and payload[1] & 0xE0 == 0xE0)
    )


def _request_audio(text: str, model: str) -> tuple[bytes, str]:
    api_key = user_settings.llm_api_key(app_config.LLM_PROVIDER_OPENROUTER)
    if not api_key:
        raise RuntimeError("Set an OpenRouter API key in Settings to use Practice TTS.")
    if model not in app_config.INTERVIEW_TTS_MODELS or model not in TTS_CAPABILITIES:
        raise RuntimeError("That Practice TTS model is not supported.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": (os.environ.get("OPENROUTER_APP_NAME") or "MacroQuantLedger Interview Practice").strip(),
    }
    referer = (os.environ.get("OPENROUTER_HTTP_REFERER") or "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    capability = TTS_CAPABILITIES[model]
    attempts = [
        {
            "model": model, "input": text, "voice": voice,
            "response_format": capability.response_format,
        }
        for voice in capability.voices
    ]
    # Some upstream adapters provide a default voice but reject an explicit
    # voice field. This final minimal request is attempted only after a clear
    # 400/422 option-validation response, never after auth/rate/server errors.
    attempts.append({
        "model": model, "input": text,
        "response_format": capability.response_format,
    })

    response = None
    for index, request_payload in enumerate(attempts):
        response = requests.post(
            f"{_base_url()}/audio/speech",
            headers=headers,
            json=request_payload,
            timeout=75,
        )
        if response.ok:
            break
        if response.status_code not in {400, 422} or index == len(attempts) - 1:
            break
        error_text = response.text.lower()
        if not any(term in error_text for term in (
            "voice", "option", "parameter", "unsupported", "invalid", "unknown",
        )):
            break

    if response is None or not response.ok:
        try:
            payload = response.json()
            detail = payload.get("error", {}).get("message") or payload.get("message")
        except (ValueError, AttributeError):
            detail = response.text[:300]
        raise RuntimeError(detail or f"OpenRouter TTS returned HTTP {response.status_code}.")
    if not response.content:
        raise RuntimeError("OpenRouter TTS returned empty audio.")
    if capability.response_format == "pcm":
        if not capability.pcm_sample_rate:
            raise RuntimeError("The TTS model is missing its PCM playback capability metadata.")
        return _pcm_to_mp3(response.content, capability.pcm_sample_rate), "audio/mpeg"
    if not _is_mp3(response.content):
        raise RuntimeError("The TTS provider did not return valid MP3 audio.")
    return response.content, response.headers.get("Content-Type", "audio/mpeg")


def register_interview_tts_routes(app) -> None:
    """Register the local, key-protecting TTS proxy route once."""
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return
    _ROUTES_REGISTERED = True

    @app.post("/api/interview/tts")
    async def synthesize_interview_question(payload: dict):
        text = str(payload.get("text") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="The question is empty.")
        if len(text) > MAX_TTS_CHARS:
            raise HTTPException(status_code=413, detail="The question is too long for TTS.")
        try:
            audio, media_type = await run_in_threadpool(_request_audio, text, model)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(content=audio, media_type=media_type)
