"""Optional LLM polish and briefing generation via OpenRouter.

Requires OPENROUTER_API_KEY. Base URL, models, token limits, and temperature are
set in config.py and overridden by environment variables (documented in CLAUDE.md).
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

_BRIEFING_SYSTEM = (
    "You are a senior macro-quant strategist writing a spoken morning briefing for an investment committee. "
    "Using the structured view data provided, write a coherent, meeting-ready briefing in flowing prose. "
    "Requirements: first person and direct; 4–6 paragraphs of 2–4 sentences each; open with a one-paragraph "
    "macro overview that captures the dominant theme; weave the individual views together naturally rather "
    "than enumerating them one by one; incorporate supporting data where it strengthens the narrative; "
    "close with one paragraph on asset posture implications. "
    "No bullet points. No headers. No preamble or meta-commentary. "
    "Spoken style — this will be read aloud in a meeting."
)


def _strip_env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _openrouter_api_key() -> str:
    return _strip_env("OPENROUTER_API_KEY")


def _base_url() -> str:
    return _strip_env("OPENROUTER_BASE_URL") or app_config.OPENROUTER_BASE_URL_DEFAULT


def _model_polish() -> str:
    return (
        _strip_env("OPENROUTER_POLISH_MODEL")
        or _strip_env("OPENROUTER_MODEL")
        or app_config.OPENROUTER_MODEL_DEFAULT
    )


def _model_briefing() -> str:
    return (
        _strip_env("OPENROUTER_BRIEFING_MODEL")
        or _strip_env("OPENROUTER_MODEL")
        or app_config.OPENROUTER_MODEL_DEFAULT
    )


def _env_int(name: str, default: int) -> int:
    v = _strip_env(name)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = _strip_env(name)
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _max_tokens_polish() -> int:
    return _env_int("OPENROUTER_MAX_TOKENS_POLISH", app_config.OPENROUTER_MAX_TOKENS_POLISH)


def _max_tokens_briefing() -> int:
    return _env_int("OPENROUTER_MAX_TOKENS_BRIEFING", app_config.OPENROUTER_MAX_TOKENS_BRIEFING)


def _temperature() -> float:
    return _env_float("OPENROUTER_TEMPERATURE", float(app_config.OPENROUTER_TEMPERATURE))


def available() -> bool:
    return bool(_openrouter_api_key())


def _cache_digest(base_url: str, model: str, text: str) -> str:
    raw = f"{base_url}\n{model}\n{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


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


def _openrouter_client():
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError(
            "The `openai` package is not installed. Run: pip install openai"
        ) from e

    key = _openrouter_api_key()
    base = _base_url()
    headers: dict[str, str] = {}
    referer = _strip_env("OPENROUTER_HTTP_REFERER")
    if referer:
        headers["HTTP-Referer"] = referer
    headers["X-Title"] = _strip_env("OPENROUTER_APP_NAME") or "MacroQuantLedger"
    return OpenAI(api_key=key, base_url=base, default_headers=headers)


def _message_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            t = block.get("type")
            if t == "text" and "text" in block:
                parts.append(str(block["text"]))
        elif hasattr(block, "type") and getattr(block, "type", None) == "text":
            parts.append(str(getattr(block, "text", "")))
    return "\n".join(parts).strip()


def _chat(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
) -> tuple[str | None, str | None]:
    try:
        client = _openrouter_client()
    except ImportError as e:
        return None, str(e)
    except Exception as e:
        return None, f"OpenRouter client init failed: {type(e).__name__}: {e}"[:800]
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=_temperature(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _log.warning("OpenRouter chat failed (model=%s): %s", model, err, exc_info=_log.isEnabledFor(logging.DEBUG))
        return None, err[:800]
    if not resp.choices:
        return None, "OpenRouter returned no choices."
    msg = resp.choices[0].message
    text = _message_text(getattr(msg, "content", None))
    if not text:
        return None, "Model returned empty content."
    return text, None


def polish(text: str, force: bool = False) -> tuple[str | None, str | None]:
    """Synchronous. Call via run.io_bound from NiceGUI.

    Returns (polished_text, error_message). error_message is None on success.
    Pass force=True to bypass the cache and always call the API.
    """
    if not _openrouter_api_key():
        return (
            None,
            "OPENROUTER_API_KEY is empty for this Python process (set it before starting the app).",
        )
    base = _base_url()
    model = _model_polish()
    cache = _load_cache()
    k = _cache_digest(base, model, text)
    if not force and k in cache:
        return cache[k], None
    result, err = _chat(model, _SYSTEM, text, _max_tokens_polish())
    if err or not result:
        return None, err or "Unknown error"
    cache[k] = result
    _write_cache(cache)
    return result, None


def get_cached(text: str) -> str | None:
    """Return cached polish for text, or None if not yet polished."""
    if not _openrouter_api_key():
        return None
    base = _base_url()
    model = _model_polish()
    k = _cache_digest(base, model, text)
    return _load_cache().get(k)


def generate_briefing(context: str, force: bool = False) -> tuple[str | None, str | None]:
    """Generate a full meeting briefing from all macro + asset context. Synchronous — use run.io_bound."""
    if not _openrouter_api_key():
        return None, "OPENROUTER_API_KEY is not set."
    base = _base_url()
    model = _model_briefing()
    cache = _load_cache()
    k = "full_" + _cache_digest(base, model, context)
    if not force and k in cache:
        return cache[k], None
    result, err = _chat(model, _BRIEFING_SYSTEM, context, _max_tokens_briefing())
    if err or not result:
        return None, err or "Unknown error"
    cache[k] = result
    _write_cache(cache)
    return result, None


def get_cached_briefing(context: str) -> str | None:
    """Return cached full briefing for this context hash, or None."""
    if not _openrouter_api_key():
        return None
    base = _base_url()
    model = _model_briefing()
    k = "full_" + _cache_digest(base, model, context)
    return _load_cache().get(k)
