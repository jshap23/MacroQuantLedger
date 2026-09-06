"""User-editable local settings kept separate from research state."""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

import config as app_config


SETTINGS_FILE = Path(__file__).resolve().parent.parent / "data" / "user_settings.json"
_LOCK = RLock()


def load_user_settings() -> dict:
    with _LOCK:
        try:
            value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, ValueError, OSError):
            return {}


def obsidian_export_path() -> Path | None:
    raw = (
        (os.environ.get("OBSIDIAN_EXPORT_PATH") or "").strip()
        or str(load_user_settings().get("obsidian_export_path") or "").strip()
        or app_config.OBSIDIAN_EXPORT_PATH_DEFAULT.strip()
    )
    return Path(raw).expanduser() if raw else None


def obsidian_views_folder() -> Path | None:
    raw = (
        (os.environ.get("OBSIDIAN_VIEWS_FOLDER") or "").strip()
        or str(load_user_settings().get("obsidian_views_folder") or "").strip()
        or app_config.OBSIDIAN_VIEWS_FOLDER_DEFAULT.strip()
    )
    return Path(raw).expanduser() if raw else None


def save_obsidian_export_path(value: str) -> Path:
    cleaned = value.strip().strip('"')
    if not cleaned:
        raise ValueError("Enter the absolute folder where MacroQuant notes should be written.")
    path = Path(cleaned).expanduser()
    if not path.is_absolute():
        raise ValueError("Use an absolute path, for example C:\\Obsidian\\Vault\\MacroQuant.")
    with _LOCK:
        settings = load_user_settings()
        settings["obsidian_export_path"] = str(path)
        _write(settings)
    return path


def save_obsidian_views_folder(value: str) -> Path:
    cleaned = value.strip().strip('"')
    if not cleaned:
        raise ValueError("Enter the absolute Obsidian Views folder.")
    path = Path(cleaned).expanduser()
    if not path.is_absolute():
        raise ValueError("Use an absolute path, for example C:\\Obsidian\\Vault\\Views.")
    with _LOCK:
        settings = load_user_settings()
        settings["obsidian_views_folder"] = str(path)
        _write(settings)
    return path


def _strip(value: str | None) -> str:
    return (value or "").strip()


def _provider_env_name(provider: str) -> str:
    if provider == app_config.LLM_PROVIDER_OPENCODE_GO:
        return "OPENCODE_API_KEY"
    return "OPENROUTER_API_KEY"


def llm_provider() -> str:
    env = _strip(os.environ.get("MQLEDGER_LLM_PROVIDER"))
    if env in {app_config.LLM_PROVIDER_OPENROUTER, app_config.LLM_PROVIDER_OPENCODE_GO}:
        return env
    stored = _strip(load_user_settings().get("llm_provider"))
    if stored in {app_config.LLM_PROVIDER_OPENROUTER, app_config.LLM_PROVIDER_OPENCODE_GO}:
        return stored
    return app_config.LLM_PROVIDER_DEFAULT


def save_llm_provider(value: str) -> None:
    cleaned = _strip(value)
    if cleaned not in {app_config.LLM_PROVIDER_OPENROUTER, app_config.LLM_PROVIDER_OPENCODE_GO}:
        raise ValueError(f"Choose '{app_config.LLM_PROVIDER_OPENROUTER}' or '{app_config.LLM_PROVIDER_OPENCODE_GO}'.")
    with _LOCK:
        settings = load_user_settings()
        settings["llm_provider"] = cleaned
        _write(settings)


def llm_api_key(provider: str = "") -> str:
    provider = provider or llm_provider()
    env = _strip(os.environ.get(_provider_env_name(provider)))
    if env:
        return env
    return _strip(load_user_settings().get(f"{provider}_api_key"))


def save_llm_api_key(provider: str, value: str) -> None:
    cleaned = _strip(value)
    key = f"{provider}_api_key"
    with _LOCK:
        settings = load_user_settings()
        if cleaned:
            settings[key] = cleaned
        else:
            settings.pop(key, None)
        _write(settings)


def llm_base_url(provider: str = "") -> str:
    provider = provider or llm_provider()
    if provider == app_config.LLM_PROVIDER_OPENCODE_GO:
        return _strip(os.environ.get("OPENCODE_BASE_URL")) or app_config.OPENCODE_GO_BASE_URL_DEFAULT
    return _strip(os.environ.get("OPENROUTER_BASE_URL")) or app_config.OPENROUTER_BASE_URL_DEFAULT


def llm_model(provider: str = "", purpose: str = "default") -> str:
    provider = provider or llm_provider()
    purpose_env_map = {
        "default": "OPENCODE_MODEL" if provider == app_config.LLM_PROVIDER_OPENCODE_GO else "OPENROUTER_MODEL",
        "polish": "OPENCODE_POLISH_MODEL" if provider == app_config.LLM_PROVIDER_OPENCODE_GO else "OPENROUTER_POLISH_MODEL",
        "research": "OPENCODE_RESEARCH_MODEL" if provider == app_config.LLM_PROVIDER_OPENCODE_GO else "OPENROUTER_RESEARCH_MODEL",
    }
    env_key = purpose_env_map.get(purpose, purpose_env_map["default"])
    env_val = _strip(os.environ.get(env_key))
    if env_val:
        return env_val
    stored = _strip(load_user_settings().get(f"{provider}_model"))
    if stored:
        return stored
    if provider == app_config.LLM_PROVIDER_OPENCODE_GO:
        return app_config.OPENCODE_GO_MODEL_DEFAULT
    return app_config.OPENROUTER_MODEL_DEFAULT


def save_llm_model(provider: str, value: str) -> None:
    cleaned = _strip(value)
    key = f"{provider}_model"
    with _LOCK:
        settings = load_user_settings()
        if cleaned:
            settings[key] = cleaned
        else:
            settings.pop(key, None)
        _write(settings)


def research_summary_model() -> str:
    provider = llm_provider()
    env_key = "OPENCODE_RESEARCH_MODEL" if provider == app_config.LLM_PROVIDER_OPENCODE_GO else "OPENROUTER_RESEARCH_MODEL"
    raw = (
        _strip(os.environ.get(env_key))
        or _strip(load_user_settings().get("research_summary_model"))
    )
    return raw


def save_research_summary_model(value: str) -> None:
    cleaned = (value or "").strip()
    with _LOCK:
        settings = load_user_settings()
        if cleaned:
            settings["research_summary_model"] = cleaned
        else:
            settings.pop("research_summary_model", None)
        _write(settings)


def interview_tts_enabled() -> bool:
    """Whether new Practice questions should be read aloud automatically."""
    return load_user_settings().get("interview_tts_enabled") is True


def save_interview_tts_enabled(value: bool) -> None:
    with _LOCK:
        settings = load_user_settings()
        settings["interview_tts_enabled"] = bool(value)
        _write(settings)


def interview_tts_model() -> str:
    configured = _strip(os.environ.get("INTERVIEW_TTS_MODEL"))
    if configured:
        return configured
    stored = _strip(load_user_settings().get("interview_tts_model"))
    if stored in app_config.INTERVIEW_TTS_MODELS:
        return stored
    return app_config.INTERVIEW_TTS_MODEL_DEFAULT


def save_interview_tts_model(value: str) -> None:
    cleaned = _strip(value)
    if cleaned not in app_config.INTERVIEW_TTS_MODELS:
        raise ValueError("Choose one of the supported Practice TTS models.")
    with _LOCK:
        settings = load_user_settings()
        settings["interview_tts_model"] = cleaned
        _write(settings)


DEFAULT_DEPRIORITIZED_SOURCES = ["arXiv q-fin"]


def deprioritized_sources() -> set[str]:
    raw = load_user_settings().get("deprioritized_sources")
    if isinstance(raw, list):
        return {str(x) for x in raw}
    return set(DEFAULT_DEPRIORITIZED_SOURCES)


def save_deprioritized_sources(labels: list[str]) -> None:
    cleaned = sorted({str(x) for x in labels if str(x).strip()})
    with _LOCK:
        settings = load_user_settings()
        settings["deprioritized_sources"] = cleaned
        _write(settings)


def _write(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = SETTINGS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    temp.replace(SETTINGS_FILE)
