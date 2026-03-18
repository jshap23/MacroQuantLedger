from __future__ import annotations
from datetime import datetime, timezone
from nicegui import ui
from models.schema import AppState, MacroView
from storage.persistence import save_state
from components.status_bar import days_since, staleness_color


# Direction: prominent colored badge
DIRECTION_COLORS = {
    "Bullish":  {"bg": "#1a6b3a", "text": "#4ade80", "dot": "#4ade80"},
    "Neutral":  {"bg": "#2a2a38", "text": "#a0a0b8", "dot": "#a0a0b8"},
    "Bearish":  {"bg": "#6b1a1a", "text": "#f87171", "dot": "#f87171"},
    "No View":  {"bg": "#1e1e24", "text": "#555566", "dot": "#555566"},
}

# Conviction: small subtle indicator dots
CONVICTION_DOTS = {
    "High":   ("●●●", "#4a8fe8"),
    "Medium": ("●●○", "#4a8fe8"),
    "Low":    ("●○○", "#4a8fe8"),
    "—":      ("○○○", "#333344"),
}

FLAG_MAP = {
    "Coherent":     "green",
    "Tension":      "yellow",
    "Inconsistent": "red",
}
FLAG_DISPLAY = {v: k for k, v in FLAG_MAP.items()}
FLAG_COLORS = {
    "green":  "#4ade80",
    "yellow": "#facc15",
    "red":    "#f87171",
}


def render_macro_views(state: AppState, save_indicator):
    def save():
        save_state(state)
        save_indicator()

    with ui.column().classes("w-full").style("gap:0; padding:0;"):
        for view in state.macro_views:
            _render_card(view, state, save)

        ui.label("NOTES").classes("section-header").style("margin-top:2rem;")
        notes_area = ui.textarea(
            placeholder="Cross-cutting themes, half-formed ideas, anything that doesn't fit neatly into a single variable…"
        ).classes("w-full dark-input").style("min-height:120px;")
        notes_area.value = state.macro_notes

        def on_notes_blur():
            state.macro_notes = notes_area.value
            save()

        notes_area.on("blur", lambda _: on_notes_blur())


def _render_card(view: MacroView, state: AppState, save):
    expanded = {"v": False}

    with ui.column().classes("w-full macro-card"):
        header = ui.row().classes("w-full macro-card-header")
        body = ui.column().classes("w-full macro-card-body").style("display:none;")

        def toggle(e, h=header, b=body, ed=expanded, v=view):
            ed["v"] = not ed["v"]
            if ed["v"]:
                b.style("display:flex; flex-direction:column; gap:0; border-top:1px solid var(--border); "
                        "background:var(--bg-primary); padding:0.85rem 1rem 1rem;")
            else:
                b.style("display:none;")
            _rebuild_header(h, v, ed["v"])

        header.on("click", toggle)

        with header:
            _build_header_contents(view, expanded["v"])

        with body:
            _render_body(view, state, save)


def _build_header_contents(view: MacroView, is_expanded: bool):
    dc = DIRECTION_COLORS.get(view.direction, DIRECTION_COLORS["No View"])
    dots, dot_color = CONVICTION_DOTS.get(view.conviction, CONVICTION_DOTS["—"])
    d = days_since(view.last_touched)
    s_label = "never" if d is None else ("today" if d == 0 else f"{d}d ago")
    s_color = staleness_color(d)
    flag_color = FLAG_COLORS.get(view.flag, "#555")

    # Direction badge (prominent)
    ui.element("span").style(
        f"background:{dc['bg']}; color:{dc['text']}; padding:3px 10px; border-radius:4px; "
        f"font-size:0.75rem; font-weight:700; letter-spacing:0.05em; "
        f"border:1px solid {dc['text']}22; white-space:nowrap; flex-shrink:0;"
    ).text = view.direction

    # Variable name
    ui.label(view.name).style(
        "font-weight:700; font-size:0.95rem; flex-shrink:0; min-width:150px;"
    )

    # Lean preview (fills space)
    if view.lean:
        ui.label(view.lean).style(
            "font-style:italic; color:var(--text-muted); font-size:0.82rem; "
            "flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0;"
        )
    else:
        ui.element("span").style("flex:1;")

    # Conviction dots (subtle)
    ui.element("span").style(
        f"color:{dot_color}; font-size:0.7rem; letter-spacing:2px; "
        f"flex-shrink:0; opacity:0.85; margin-right:4px; font-family:monospace;"
    ).text = dots

    # Flag dot
    ui.element("span").style(
        f"width:8px; height:8px; border-radius:50%; background:{flag_color}; "
        f"display:inline-block; flex-shrink:0; opacity:0.7;"
    )

    # Staleness
    ui.label(s_label).style(
        f"color:{s_color}; font-size:0.75rem; white-space:nowrap; flex-shrink:0; min-width:55px; text-align:right;"
    )

    # Arrow
    ui.label("▲" if is_expanded else "▼").style(
        "color:var(--text-muted); font-size:0.7rem; flex-shrink:0;"
    )


def _rebuild_header(header, view: MacroView, is_expanded: bool):
    header.clear()
    with header:
        _build_header_contents(view, is_expanded)


def _render_body(view: MacroView, state: AppState, save):
    def update_and_save():
        view.last_touched = datetime.now(tz=timezone.utc)
        save()

    # Name
    ui.label("VARIABLE NAME").classes("field-label")
    name_input = ui.input(value=view.name).classes("w-full dark-input")
    name_input.on("blur", lambda _, v=view, ni=name_input: (
        setattr(v, "name", ni.value), update_and_save()
    ))

    # Lean
    ui.label("DIRECTIONAL LEAN").classes("field-label")
    lean_input = ui.textarea(
        value=view.lean,
        placeholder="One sentence — direction, magnitude, where uncertainty sits…"
    ).classes("w-full dark-input")
    lean_input.on("blur", lambda _, v=view, li=lean_input: (
        setattr(v, "lean", li.value), update_and_save()
    ))

    # Signals
    ui.label("THREE SUPPORTING SIGNALS").classes("field-label")
    signal_inputs = []
    for i in range(3):
        si = ui.input(
            value=view.signals[i] if i < len(view.signals) else "",
            placeholder="Data point, model output, or market behavior…"
        ).classes("w-full dark-input").style("margin-bottom:4px;")
        signal_inputs.append(si)

    def save_signals(v=view, sis=signal_inputs):
        v.signals = [s.value for s in sis]
        update_and_save()

    for si in signal_inputs:
        si.on("blur", lambda _, fn=save_signals: fn())

    # Counter
    ui.label("THE COUNTER").classes("field-label")
    counter_input = ui.textarea(
        value=view.counter,
        placeholder="Best argument against your own view…"
    ).classes("w-full dark-input")
    counter_input.on("blur", lambda _, v=view, ci=counter_input: (
        setattr(v, "counter", ci.value), update_and_save()
    ))

    # View direction + Conviction + Flag
    with ui.row().classes("w-full").style("gap:1rem; margin-top:0.75rem;"):
        with ui.column().style("flex:1; gap:0;"):
            ui.label("VIEW").classes("field-label")
            ui.select(
                ["Bullish", "Neutral", "Bearish", "No View"],
                value=view.direction,
                on_change=lambda e, v=view: (
                    setattr(v, "direction", e.value), update_and_save()
                )
            ).classes("w-full dark-input")

        with ui.column().style("flex:1; gap:0;"):
            ui.label("CONVICTION").classes("field-label")
            ui.select(
                ["High", "Medium", "Low", "—"],
                value=view.conviction,
                on_change=lambda e, v=view: (
                    setattr(v, "conviction", e.value), update_and_save()
                )
            ).classes("w-full dark-input")

        with ui.column().style("flex:1; gap:0;"):
            ui.label("CONSISTENCY FLAG").classes("field-label")
            ui.select(
                ["Coherent", "Tension", "Inconsistent"],
                value=FLAG_DISPLAY.get(view.flag, "Coherent"),
                on_change=lambda e, v=view: (
                    setattr(v, "flag", FLAG_MAP.get(e.value, "green")), update_and_save()
                )
            ).classes("w-full dark-input")
