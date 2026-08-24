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
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = SETTINGS_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        temp.replace(SETTINGS_FILE)
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
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = SETTINGS_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        temp.replace(SETTINGS_FILE)
    return path
