from __future__ import annotations
from datetime import datetime, timezone
from nicegui import ui
from models.schema import AppState


def days_since(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    now = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days


def staleness_color(days: int | None) -> str:
    if days is None:
        return "#f87171"   # red
    if days <= 14:
        return "#4ade80"   # green
    if days <= 28:
        return "#fbbf24"   # amber
    if days <= 42:
        return "#fb923c"   # orange
    return "#f87171"       # red


def staleness_label(days: int | None) -> str:
    if days is None:
        return "never"
    if days == 0:
        return "today"
    if days == 1:
        return "1d ago"
    return f"{days}d ago"


def render_status_bar(state: AppState):
    # VIEWS CURRENT (touched within 14 days)
    current_count = sum(
        1 for v in state.macro_views
        if v.last_touched is not None and days_since(v.last_touched) <= 14
    )
    stale_color = "#4ade80" if current_count == 7 else ("#fbbf24" if current_count >= 5 else "#f87171")

    # LAST RECONCILIATION
    recon_days = None
    if state.reconciliations:
        recon_days = days_since(state.reconciliations[0].date)
    recon_color = (
        "#4ade80" if recon_days is not None and recon_days <= 7
        else "#fbbf24" if recon_days is not None and recon_days <= 10
        else "#f87171"
    )
    recon_label = staleness_label(recon_days)

    with ui.row().classes("status-bar"):
        _indicator("VIEWS CURRENT", f"{current_count}/7", stale_color)
        _indicator("LAST RECONCILIATION", recon_label, recon_color)


def _indicator(label: str, value: str, color: str):
    with ui.element("div").classes("status-indicator"):
        ui.label(label).classes("status-label")
        ui.label(value).style(f"color: {color}; font-weight: 700; font-size: 1rem;")
