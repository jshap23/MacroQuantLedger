from __future__ import annotations
import json
from pathlib import Path
from models.schema import AppState, default_state

DATA_DIR = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "state.json"


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> AppState:
    ensure_data_dir()
    if not STATE_FILE.exists():
        state = default_state()
        save_state(state)
        return state
    try:
        raw = STATE_FILE.read_text(encoding="utf-8")
        return AppState.model_validate_json(raw)
    except Exception:
        state = default_state()
        save_state(state)
        return state


def save_state(state: AppState):
    ensure_data_dir()
    STATE_FILE.write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )
