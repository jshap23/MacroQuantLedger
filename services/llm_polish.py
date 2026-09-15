"""Optional LLM polish for summaries and briefings.

Supports OpenRouter and OpenCode Go. Provider, API key, base URL, and models are
read from storage/user_settings.json with environment-variable overrides.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
from pathlib import Path

import config as app_config
from storage import user_settings

_log = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "briefing_cache.json"

_SYSTEM = (
    "You are a concise editor for spoken finance briefings. "
    "Rewrite the provided talking point into fluent, confident spoken prose "
    "a presenter would say aloud in a meeting. "
    "Keep all substance and data intact. "
    "Write one paragraph of 3–5 sentences. No bullet points. No preamble or meta-commentary."
)


def _strip_env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _provider() -> str:
    return user_settings.llm_provider()


def _api_key() -> str:
    return user_settings.llm_api_key(_provider())


def _base_url() -> str:
    return user_settings.llm_base_url(_provider())


def _model(purpose: str = "default") -> str:
    return user_settings.llm_model(_provider(), purpose=purpose)


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


def _temperature() -> float:
    return _env_float("OPENROUTER_TEMPERATURE", float(app_config.OPENROUTER_TEMPERATURE))


def available() -> bool:
    return bool(_api_key())


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


def _llm_client():
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError(
            "The `openai` package is not installed. Run: pip install openai"
        ) from e

    provider = _provider()
    key = _api_key()
    base = _base_url()
    headers: dict[str, str] = {}
    if provider == app_config.LLM_PROVIDER_OPENROUTER:
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
    provider_label = _provider_label()
    try:
        client = _llm_client()
    except ImportError as e:
        return None, str(e)
    except Exception as e:
        return None, f"{provider_label} client init failed: {type(e).__name__}: {e}"[:800]
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": _temperature(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        try:
            # Reasoning tokens are charged against max_tokens, so leaving
            # reasoning on spends most of the polish budget before any prose
            # is written. The SDK forwards extra_body verbatim.
            resp = client.chat.completions.create(
                **kwargs, extra_body={"reasoning": {"enabled": False}}
            )
        except Exception as exc:
            if "reasoning" not in str(exc).lower():
                raise
            resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _log.warning("%s chat failed (model=%s): %s", provider_label, model, err, exc_info=_log.isEnabledFor(logging.DEBUG))
        return None, err[:800]
    if not resp.choices:
        return None, f"{provider_label} returned no choices."
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
    if not _api_key():
        return (
            None,
            f"{_provider_label()} API key is empty. Set it via environment variable or in Settings.",
        )
    base = _base_url()
    model = _model("polish")
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
    if not _api_key():
        return None
    base = _base_url()
    model = _model("polish")
    k = _cache_digest(base, model, text)
    return _load_cache().get(k)


# ── Document summaries (Fed Watch tab) ────────────────────────────────────────

_SUMMARY_SYSTEM = (
    "You are a macro research analyst summarizing a Federal Reserve "
    "communication for a portfolio manager who has not read it. Cover: the "
    "policy stance and any change versus prior guidance, the 3-5 most "
    "substantive points, notable language or tone shifts, and one closing "
    "line on market implications. Plain prose, compact paragraphs or short "
    "bullets. No preamble, no meta-commentary."
)

_SUMMARY_PREFIX = "SUMMARY::"
_MAX_DOC_CHARS = 30000


def _doc_key(text: str) -> tuple[str, str]:
    base = _base_url()
    model = _model("default")
    trimmed = text.strip()[:_MAX_DOC_CHARS]
    return _cache_digest(base, model, _SUMMARY_PREFIX + trimmed), trimmed


def summarize(text: str, force: bool = False) -> tuple[str | None, str | None]:
    """Synchronous. Call via run.io_bound from NiceGUI.

    Returns (summary, error_message). Cached like polish(); force bypasses.
    """
    if not _api_key():
        return (
            None,
            f"{_provider_label()} API key is empty. Set it via environment variable or in Settings.",
        )
    if not (text or "").strip():
        return None, "No readable text available for this document."
    key, trimmed = _doc_key(text)
    cache = _load_cache()
    if not force and key in cache:
        return cache[key], None
    result, err = _chat(_model("default"), _SUMMARY_SYSTEM, trimmed, max(900, _max_tokens_polish()))
    if err or not result:
        return None, err or "Unknown error"
    cache[key] = result
    _write_cache(cache)
    return result, None


def get_cached_summary(text: str) -> str | None:
    """Return cached summary for document text, or None if not yet generated."""
    if not _api_key() or not (text or "").strip():
        return None
    key, _ = _doc_key(text)
    return _load_cache().get(key)


# ── Research-paper key takeaways (Papers tab) ────────────────────────────────

_PAPER_SYSTEM = (
    "You are a macro research analyst screening an economics paper for a "
    "portfolio manager. You are usually given only the title, authors, and "
    "abstract — stay grounded in what is provided and never invent results, "
    "data details, or conclusions. Return 3-5 short bullets: the core "
    "finding; the data and method in one line; the implication for markets, "
    "policy, or macro views; and one line on how much weight the finding "
    "deserves and why. Start each bullet with '- '. No preamble, no closing."
)

_PAPER_PREFIX = "PAPER::"


def paper_model() -> str:
    return user_settings.research_summary_model() or _model("polish")


def paper_endpoint() -> str:
    from urllib.parse import urlsplit
    base = _base_url()
    try:
        return urlsplit(base).netloc or base
    except Exception:
        return base


def paper_provenance() -> dict[str, str]:
    return {"model": paper_model(), "endpoint": paper_endpoint()}


def _paper_key(text: str) -> tuple[str, str]:
    trimmed = text.strip()[:_MAX_DOC_CHARS]
    return (
        _cache_digest(_base_url(), paper_model(), _PAPER_PREFIX + trimmed),
        trimmed,
    )


def summarize_paper(text: str, force: bool = False) -> tuple[str | None, str | None]:
    """Key takeaways for a paper. Synchronous; call via run.io_bound.

    Returns (takeaways, error_message). Cached like summarize().
    """
    if not available():
        return None, "LLM API key is not configured."
    if not (text or "").strip():
        return None, "No abstract available for this paper."
    key, trimmed = _paper_key(text)
    cache = _load_cache()
    if not force and key in cache:
        return cache[key], None
    result, err = _chat(paper_model(), _PAPER_SYSTEM, trimmed, max(900, _max_tokens_polish()))
    if err or not result:
        return None, err or "Unknown error"
    cache[key] = result
    _write_cache(cache)
    return result, None


