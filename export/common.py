"""Shared helpers for export modules. Pure functions only — no I/O."""
from __future__ import annotations

from datetime import datetime

from models.schema import AppState, AssetView


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d")
    return str(dt)


def pipe_safe(s: str) -> str:
    """Escape pipe characters so they don't break markdown tables."""
    return s.replace("|", "\\|") if s else ""


def asset_groups(state: AppState) -> list[tuple[str, str, list[AssetView]]]:
    """Return (group_key, group_label, views) tuples in display order."""
    return [
        (key, label, [v for v in state.asset_views if v.group == key])
        for key, label in [
            ("l1", "Level 1 — Cross-Asset"),
            ("equities", "Equities"),
            ("fixed_income", "Fixed Income"),
        ]
    ]
