"""Optional LLM polish for talking points.

Requires ANTHROPIC_API_KEY in the process environment. Model id is set in
config.ANTHROPIC_POLISH_MODEL (not via environment variables).
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
from pathlib import Path

import config as app_config

_log = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "briefing_cache.json"

_SYSTEM = (
    "You are a concise editor for spoken finance briefings. "
    "Rewrite the provided talking point into fluent, confident spoken prose "
    "a presenter would say aloud in a meeting. "
    "Keep all substance and data intact. "
    "Write one paragraph of 3–5 sentences. No bullet points. No preamble or meta-commentary."
)


def _api_key() -> str:
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def available() -> bool:
    return bool(_api_key())


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def _assistant_text(msg) -> str:
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text" and hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts).strip()


def polish(text: str) -> tuple[str | None, str | None]:
    """Synchronous. Call via run.io_bound from NiceGUI.

    Returns (polished_text, error_message). error_message is None on success.
    """
    key = _api_key()
    if not key:
        return None, "ANTHROPIC_API_KEY is empty for this Python process (set it before starting the app)."
    cache = _load_cache()
    k = _cache_key(text)
    if k in cache:
        return cache[k], None
    try:
        import anthropic
    except ImportError as e:
        msg = (
            "The `anthropic` package is not installed in this environment. "
            "Run: pip install anthropic"
        )
        _log.warning("llm_polish: %s (%s)", msg, e)
        return None, msg
    try:
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=app_config.ANTHROPIC_POLISH_MODEL,
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        result = _assistant_text(msg)
        if not result:
            err = "Model returned no text blocks."
            _log.warning("llm_polish: %s", err)
            return None, err
        cache[k] = result
        _write_cache(cache)
        return result, None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _log.warning("Anthropic polish failed: %s", err, exc_info=_log.isEnabledFor(logging.DEBUG))
        return None, err[:800]


def get_cached(text: str) -> str | None:
    """Return cached polish for text, or None if not yet polished."""
    if not _api_key():
        return None
    return _load_cache().get(_cache_key(text))
