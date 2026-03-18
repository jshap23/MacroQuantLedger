from __future__ import annotations
import json
import shutil
from datetime import date
from pathlib import Path
from models.schema import AppState, default_state, DEFAULT_ASSET_VIEWS

DATA_DIR = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "state.json"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _daily_snapshot():
    """Copy current state.json to snapshots/state_YYYY-MM-DD.json once per day.

    The snapshot captures the state at the *start* of the day — before any
    edits — so it represents what you had going into that session.
    """
    if not STATE_FILE.exists():
        return
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = SNAPSHOTS_DIR / f"state_{date.today().isoformat()}.json"
    if not snapshot.exists():
        shutil.copy2(STATE_FILE, snapshot)


def _migrate(state: AppState) -> AppState:
    """Handle schema migrations so old state.json files load cleanly."""
    changed = False
    valid_directions = {"Bullish", "Neutral", "Bearish", "No View"}
    valid_convictions = {"High", "Medium", "Low", "—"}

    # Seed asset_views if missing (new field)
    if not state.asset_views:
        state.asset_views = [v.model_copy() for v in DEFAULT_ASSET_VIEWS]
        changed = True

    # Migrate asset_view directions from old Bullish/Neutral/Bearish to 1-5 score
    valid_scores = {"1", "2", "3", "4", "5", "—"}
    for av in state.asset_views:
        if av.direction not in valid_scores:
            av.direction = "—"
            changed = True

    for v in state.macro_views:
        # Old schema stored conviction as "No View"/"High"/"Medium"/"Low" (no direction field).
        # If direction is missing/invalid, it defaults to "No View" — that's fine.
        # If conviction landed as "No View" (old default), reset it to "—".
        if v.conviction not in valid_convictions:
            v.conviction = "—"
            changed = True
        if v.direction not in valid_directions:
            v.direction = "No View"
            changed = True
    if changed:
        save_state(state)
    return state


def load_state() -> AppState:
    ensure_data_dir()
    if not STATE_FILE.exists():
        state = default_state()
        save_state(state)
        return state
    try:
        raw = STATE_FILE.read_text(encoding="utf-8")
        state = AppState.model_validate_json(raw)
        return _migrate(state)
    except Exception:
        state = default_state()
        save_state(state)
        return state


def save_state(state: AppState):
    ensure_data_dir()
    _daily_snapshot()
    STATE_FILE.write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )


def import_state(json_str: str) -> AppState:
    """Validate, migrate, persist, and return state from a JSON string.

    Raises ValueError with a human-readable message on bad input.
    """
    try:
        new_state = AppState.model_validate_json(json_str)
    except Exception as exc:
        raise ValueError(f"Invalid state file: {exc}") from exc
    new_state = _migrate(new_state)
    save_state(new_state)
    return new_state
