from __future__ import annotations

from datetime import datetime, timezone

from nicegui import ui

from components.briefing_strip import render_briefing_strip
from components.status_bar import days_since
from models.schema import AppState


def _reconciliation_age(state: AppState) -> int | None:
    if not state.reconciliations:
        return None
    return days_since(state.reconciliations[0].date)


def _metric_card(value: str, label: str, detail: str, on_click) -> None:
    card = ui.element("button").classes("today-metric-card")
    card.on("click", lambda _: on_click())
    with card:
        with ui.element("div").classes("today-metric-topline"):
            ui.label(value).classes("today-metric-value")
            ui.label("→").classes("today-metric-arrow")
        ui.label(label).classes("today-metric-label")
        ui.label(detail).classes("today-metric-detail")


def render_today(state: AppState, save_indicator, navigate) -> None:
    now = datetime.now(tz=timezone.utc)
    hour = now.astimezone().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"

    stale_macro = sum(
        1 for view in state.macro_views
        if (age := days_since(view.last_touched)) is None or age > 28
    )
    set_macro = sum(1 for view in state.macro_views if view.direction != "No View")
    scored_assets = sum(1 for view in state.asset_views if view.direction not in {"—", "No View"})
    open_trades = sum(1 for trade in state.trades if trade.exit_date is None)
    recon_age = _reconciliation_age(state)

    with ui.element("section").classes("today-hero"):
        ui.label(greeting).classes("today-eyebrow")
        ui.label("Your research desk, at a glance.").classes("today-title")
        ui.label(
            "Capture the lead thought, refresh what is stale, then move into the detail only when you need it."
        ).classes("today-copy")

    render_briefing_strip(state, save_indicator)

    ui.label("DESK STATUS").classes("section-header").style("margin-top:0.5rem;")
    with ui.element("div").classes("today-metric-grid"):
        _metric_card(
            f"{set_macro}/{len(state.macro_views)}",
            "Macro views set",
            f"{stale_macro} need review" if stale_macro else "Everything is current",
            lambda: navigate("views", "macro"),
        )
        _metric_card(
            f"{scored_assets}/{len(state.asset_views)}",
            "Assets scored",
            "Update posture and thesis",
            lambda: navigate("views", "assets"),
        )
        _metric_card(
            str(open_trades),
            "Open positions",
            "Review sizing and P&L",
            lambda: navigate("views", "trades"),
        )
        _metric_card(
            "Never" if recon_age is None else ("Today" if recon_age == 0 else f"{recon_age}d"),
            "Since weekly review",
            "Reconcile the research process",
            lambda: navigate("review", "weekly"),
        )

    with ui.row().classes("today-actions"):
        ui.button(
            "Open morning briefing", icon="auto_awesome",
            on_click=lambda: navigate("research", "briefing"),
        ).classes("submit-btn")
        ui.button(
            "Review attribution", icon="query_stats",
            on_click=lambda: navigate("review", "attribution"),
        ).classes("cancel-btn")
