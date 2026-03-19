from __future__ import annotations
from datetime import datetime, timezone
from nicegui import ui
from models.schema import AppState
from storage.persistence import save_state
from components.status_bar import days_since, staleness_color, staleness_label


def render_briefing_strip(state: AppState, save_indicator):
    def save():
        save_state(state)
        save_indicator()

    b = state.briefing

    def current_age():
        d = days_since(b.top_of_mind_touched)
        return staleness_label(d) if d is not None else "never", staleness_color(d)

    with ui.row().style(
        "align-items:baseline; justify-content:space-between; width:100%; "
        "border-bottom:1px solid var(--border); padding-bottom:0.3rem; margin-bottom:0.6rem;"
    ):
        ui.label("TOP OF MIND").style(
            "font-size:0.72rem; font-weight:700; color:var(--accent); "
            "letter-spacing:0.18em; font-family:'IBM Plex Mono',monospace;"
        )
        age_text, age_color = current_age()
        age_label = ui.label(age_text).style(
            f"color:{age_color}; font-size:0.65rem; font-weight:700; white-space:nowrap;"
        )

    ta = ui.textarea(
        value=b.top_of_mind,
        placeholder="What you'd lead with, what you're watching, what would change your mind…",
    ).classes("dark-input w-full").style("min-height:80px; margin-bottom:1.25rem;")

    def on_blur():
        b.top_of_mind = ta.value
        b.top_of_mind_touched = datetime.now(tz=timezone.utc)
        new_text, new_color = current_age()
        age_label.set_text(new_text)
        age_label.style(f"color:{new_color}; font-size:0.65rem; font-weight:700; white-space:nowrap;")
        save()

    ta.on("blur", lambda _: on_blur())
