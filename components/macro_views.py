from __future__ import annotations
from datetime import datetime, timezone
from nicegui import ui
from models.schema import AppState, MacroView
from storage.persistence import save_state
from components.status_bar import days_since, staleness_color


DIRECTION_COLORS = {
    "Bullish":  {"bg": "#1a6b3a", "text": "#4ade80"},
    "Neutral":  {"bg": "#2a2a38", "text": "#a0a0b8"},
    "Bearish":  {"bg": "#6b1a1a", "text": "#f87171"},
    "No View":  {"bg": "#1e1e24", "text": "#555566"},
}

CONVICTION_BARS = {"High": 3, "Medium": 2, "Low": 1, "—": 0}

_CSS_INJECTED = False


def _inject_css():
    global _CSS_INJECTED
    if _CSS_INJECTED:
        return
    _CSS_INJECTED = True
    ui.add_css("""
        .mv-grid-header {
            display: grid;
            grid-template-columns: 88px 148px 1fr 50px 66px 18px;
            gap: 0 0.7rem;
            padding: 0 0.75rem 0.35rem;
            align-items: center;
        }
        .mv-grid-row {
            display: grid;
            grid-template-columns: 88px 148px 1fr 50px 66px 18px;
            gap: 0 0.7rem;
            padding: 0.5rem 0.75rem;
            align-items: center;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            cursor: pointer;
            transition: border-color 0.12s, background 0.12s;
        }
        .mv-grid-row:hover {
            border-color: var(--border-strong);
            background: var(--bg-hover);
        }
        .mv-drawer-card {
            width: min(460px, 95vw);
            height: 100vh;
            background: var(--bg-card);
            color: var(--text-primary);
            border-left: 1px solid var(--border-strong);
            border-radius: 0;
            padding: 0;
            margin: 0;
            overflow-y: auto;
            box-shadow: -4px 0 24px rgba(0,0,0,0.35);
        }
        body.light-mode .mv-drawer-card {
            box-shadow: -4px 0 24px rgba(0,0,0,0.12);
        }
    """)


def _conviction_bars_html(conviction: str) -> str:
    filled = CONVICTION_BARS.get(conviction, 0)
    on_color = "#2dd4bf"
    off_color = "#2a2a3e"
    heights = ["7px", "11px", "15px"]
    bars = ""
    for i, h in enumerate(heights):
        color = on_color if i < filled else off_color
        bars += (
            f'<span style="display:inline-block;width:4px;height:{h};'
            f'background:{color};border-radius:1px;margin-right:2px;'
            f'vertical-align:bottom;"></span>'
        )
    return f'<span style="display:inline-flex;align-items:flex-end;">{bars}</span>'


def _build_row_contents(view: MacroView):
    dc = DIRECTION_COLORS.get(view.direction, DIRECTION_COLORS["No View"])
    d = days_since(view.last_touched)
    s_label = "never" if d is None else ("today" if d == 0 else f"{d}d ago")
    s_color = staleness_color(d)

    ui.element("span").style(
        f"background:{dc['bg']};color:{dc['text']};padding:2px 7px;border-radius:4px;"
        f"font-size:0.67rem;font-weight:700;letter-spacing:0.05em;"
        f"border:1px solid {dc['text']}33;white-space:nowrap;text-align:center;"
    ).text = view.direction

    ui.label(view.name).style(
        "font-weight:600;font-size:0.85rem;white-space:nowrap;"
        "overflow:hidden;text-overflow:ellipsis;"
    )

    if view.lean:
        ui.label(view.lean).style(
            "font-style:italic;color:var(--text-muted);font-size:0.78rem;"
            "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
        )
    else:
        ui.label("—").style("color:var(--text-faint);font-size:0.78rem;")

    ui.html(_conviction_bars_html(view.conviction))

    ui.label(s_label).style(
        f"color:{s_color};font-size:0.71rem;white-space:nowrap;text-align:right;"
    )

    ui.label("›").style(
        "color:var(--text-faint);font-size:1rem;text-align:center;line-height:1;"
    )


def render_macro_views(state: AppState, save_indicator, log_change=None):
    _inject_css()

    def save():
        save_state(state)
        save_indicator()

    row_containers: dict[str, ui.element] = {}

    # ── Side drawer (Quasar right-position dialog) ─────────────────────────────
    with ui.dialog().props('position="right" full-height').style(
        "font-family:'IBM Plex Mono',monospace;"
    ) as drawer:
        with ui.element("div").classes("mv-drawer-card"):
            drawer_body = ui.column().style("width:100%;gap:0;padding:1.25rem 1.25rem 2rem;")

    def open_drawer(view: MacroView):
        drawer_body.clear()
        with drawer_body:
            _render_drawer(view, state, save, log_change, drawer, row_containers)
        drawer.open()

    # ── Column headers ─────────────────────────────────────────────────────────
    with ui.element("div").classes("mv-grid-header"):
        for label in ["DIRECTION", "VARIABLE", "LEAN", "CONV", "UPDATED", ""]:
            ui.label(label).style(
                "font-size:0.59rem;font-weight:700;color:var(--text-faint);"
                "letter-spacing:0.14em;font-family:'IBM Plex Mono',monospace;"
            )

    # ── Grid rows ──────────────────────────────────────────────────────────────
    with ui.column().style("width:100%;gap:0.3rem;"):
        for view in state.macro_views:
            row_el = ui.element("div").classes("mv-grid-row")
            row_containers[view.id] = row_el
            with row_el:
                _build_row_contents(view)
            row_el.on("click", lambda _, v=view: open_drawer(v))

    # ── Notes ──────────────────────────────────────────────────────────────────
    ui.label("NOTES").classes("section-header").style("margin-top:2rem;")
    notes_area = ui.textarea(
        placeholder="Cross-cutting themes, half-formed ideas, anything that doesn't fit neatly into a single variable…"
    ).classes("w-full dark-input").style("min-height:120px;")
    notes_area.value = state.macro_notes

    def on_notes_blur():
        state.macro_notes = notes_area.value
        save()

    notes_area.on("blur", lambda _: on_notes_blur())


def _render_drawer(
    view: MacroView,
    state: AppState,
    save,
    log_change,
    dialog,
    row_containers: dict,
):
    def update_and_save():
        view.last_touched = datetime.now(tz=timezone.utc)
        save()
        row_el = row_containers.get(view.id)
        if row_el is not None:
            row_el.clear()
            with row_el:
                _build_row_contents(view)

    # ── Drawer header ──────────────────────────────────────────────────────────
    with ui.row().style(
        "width:100%;align-items:center;justify-content:space-between;"
        "margin-bottom:1.5rem;border-bottom:1px solid var(--border);padding-bottom:1rem;"
    ):
        ui.label(view.name).style(
            "font-size:1rem;font-weight:700;color:var(--accent);letter-spacing:0.08em;"
        )
        ui.button("✕", on_click=dialog.close).style(
            "background:transparent;color:var(--text-muted);box-shadow:none;"
            "min-width:unset;padding:0 0.5rem;font-size:1rem;line-height:1;"
        )

    # ── Direction ─────────────────────────────────────────────────────────────
    ui.label("VIEW DIRECTION").classes("field-label")
    ui.select(
        ["Bullish", "Neutral", "Bearish", "No View"],
        value=view.direction,
        on_change=lambda e, v=view: (
            log_change(v, "direction", v.direction, e.value) if log_change and v.direction != e.value else None,
            setattr(v, "direction", e.value),
            update_and_save(),
        )
    ).classes("w-full dark-input")

    # ── Conviction ────────────────────────────────────────────────────────────
    ui.label("CONVICTION").classes("field-label").style("margin-top:0.75rem;")
    ui.select(
        ["High", "Medium", "Low", "—"],
        value=view.conviction,
        on_change=lambda e, v=view: (
            log_change(v, "conviction", v.conviction, e.value) if log_change and v.conviction != e.value else None,
            setattr(v, "conviction", e.value),
            update_and_save(),
        )
    ).classes("w-full dark-input")

    # ── Lean ──────────────────────────────────────────────────────────────────
    ui.label("DIRECTIONAL LEAN").classes("field-label").style("margin-top:0.75rem;")
    lean_input = ui.textarea(
        value=view.lean,
        placeholder="One sentence — direction, magnitude, where uncertainty sits…"
    ).classes("w-full dark-input")
    lean_input.on("blur", lambda _, v=view, li=lean_input: (
        setattr(v, "lean", li.value), update_and_save()
    ))

    # ── Signals ───────────────────────────────────────────────────────────────
    ui.label("THREE SUPPORTING SIGNALS").classes("field-label").style("margin-top:0.75rem;")
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

    # ── Counter ───────────────────────────────────────────────────────────────
    ui.label("THE COUNTER").classes("field-label").style("margin-top:0.75rem;")
    counter_input = ui.textarea(
        value=view.counter,
        placeholder="Best argument against your own view…"
    ).classes("w-full dark-input")
    counter_input.on("blur", lambda _, v=view, ci=counter_input: (
        setattr(v, "counter", ci.value), update_and_save()
    ))
