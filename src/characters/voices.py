"""Gemini TTS prebuilt voices (static list from the Gemini API speech-generation docs,
checked 2026-10-21) and an optional preview call through the Interactions API."""

from __future__ import annotations

import base64
import io
import wave
from typing import Callable

import httpx

from src.gen.provider import ProviderError

# (voice name, style) in the docs' order.
VOICES: tuple[tuple[str, str], ...] = (
    ("Zephyr", "Bright"), ("Puck", "Upbeat"), ("Charon", "Informative"), ("Kore", "Firm"),
    ("Fenrir", "Excitable"), ("Leda", "Youthful"), ("Orus", "Firm"), ("Aoede", "Breezy"),
    ("Callirrhoe", "Easy-going"), ("Autonoe", "Bright"), ("Enceladus", "Breathy"),
    ("Iapetus", "Clear"), ("Umbriel", "Easy-going"), ("Algieba", "Smooth"), ("Despina", "Smooth"),
    ("Erinome", "Clear"), ("Algenib", "Gravelly"), ("Rasalgethi", "Informative"),
    ("Laomedeia", "Upbeat"), ("Achernar", "Soft"), ("Alnilam", "Firm"), ("Schedar", "Even"),
    ("Gacrux", "Mature"), ("Pulcherrima", "Forward"), ("Achird", "Friendly"),
    ("Zubenelgenubi", "Casual"), ("Vindemiatrix", "Gentle"), ("Sadachbia", "Lively"),
    ("Sadaltager", "Knowledgeable"), ("Sulafat", "Warm"),
)
VOICE_NAMES = tuple(v for v, _ in VOICES)
STYLES = dict(VOICES)

TTS_MODELS = ("gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts")
SAMPLE_RATE = 24000


def voice_label(name: str) -> str:
    return f"{name} ({STYLES[name]})" if name in STYLES else name


def build_preview_request(text: str, voice: str, model: str = TTS_MODELS[0],
                          api_base: str = "https://generativelanguage.googleapis.com/v1beta") -> tuple[str, dict]:
    if voice not in STYLES:
        raise ValueError(f"Unknown voice {voice!r}")
    body = {
        "model": model,
        "input": text,
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    return f"{api_base}/interactions", body


def _items(data: dict):
    for step in data.get("steps") or []:
        if isinstance(step, dict) and step.get("type") == "model_output":
            yield from step.get("content") or []
    yield from data.get("outputs") or []


def as_wav(raw: bytes, mime: str) -> bytes:
    """WAV bytes as-is; headerless 16-bit PCM (audio/l16, audio/pcm) gets a RIFF header."""
    if raw[:4] == b"RIFF" or "wav" in mime:
        return raw
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(raw)
    return buf.getvalue()


def parse_audio(data: dict) -> bytes:
    for item in _items(data):
        if isinstance(item, dict) and item.get("type") == "audio" and item.get("data"):
            return as_wav(base64.b64decode(item["data"]), str(item.get("mime_type") or ""))
    if data.get("status") == "failed":
        errors = data.get("errors") or []
        msg = errors[0].get("message") if errors and isinstance(errors[0], dict) else "no details"
        raise ProviderError(f"Voice preview failed: {str(msg)[:200]}")
    raise ProviderError("No audio returned for the voice preview")


def preview_voice(voice: str, text: str, key_source: Callable[[], str] | None = None,
                  transport: httpx.BaseTransport | None = None, model: str = TTS_MODELS[0],
                  timeout: float = 60.0) -> bytes:
    """Speak ``text`` with ``voice`` and return WAV bytes. Needs the user's Gemini key."""
    from src.gen.gemini_image import KEY_ID, _no_key_message, map_http_error

    if key_source is None:
        from src.keys import get_key

        key_source = lambda: get_key(KEY_ID)  # noqa: E731
    key = (key_source() or "").strip()
    if not key:
        raise ProviderError(_no_key_message())
    url, body = build_preview_request(text, voice, model)
    with httpx.Client(transport=transport, timeout=timeout) as client:
        try:
            resp = client.post(url, json=body, headers={"x-goog-api-key": key})
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network error: {type(exc).__name__}", retryable=True) from exc
    if resp.status_code >= 400:
        raise map_http_error(resp)
    try:
        data = resp.json()
    except ValueError as exc:
        raise ProviderError("Voice preview: the reply was not JSON") from exc
    return parse_audio(data)
