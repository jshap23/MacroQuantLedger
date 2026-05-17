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
    # VIEWS CURRENT — 7 color-coded dots with tooltips
    dot_data = []
    for v in state.macro_views:
        d = days_since(v.last_touched)
        dot_data.append((v.name, staleness_color(d), staleness_label(d)))

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
        _indicator_dots("VIEWS CURRENT", dot_data)
        _indicator("LAST RECONCILIATION", recon_label, recon_color)


def _indicator_dots(label: str, dot_data: list[tuple[str, str, str]]):
    with ui.element("div").classes("status-indicator"):
        ui.label(label).classes("status-label")
        with ui.row().style("gap:4px; align-items:center;"):
            for name, color, age in dot_data:
                ui.element("span").style(
                    f"width:8px; height:8px; border-radius:50%; background:{color}; "
                    f"box-shadow:0 0 4px {color}40; cursor:default;"
                ).tooltip(f"{name} — {age}")


def _indicator(label: str, value: str, color: str):
    with ui.element("div").classes("status-indicator"):
        ui.label(label).classes("status-label")
        ui.label(value).style(f"color: {color}; font-weight: 700; font-size: 1rem;")
