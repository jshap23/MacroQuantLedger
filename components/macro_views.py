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

STARTER_GUIDANCE = {
    "growth": {
        "lean": "Set a 3–6 month US growth thesis",
        "signals": ["Payrolls, hours, and claims", "ISM new orders", "Real income and consumption"],
        "counter": "What would change your growth regime call?",
    },
    "global_growth": {
        "lean": "Define the global growth impulse",
        "signals": ["Global PMIs", "Trade and export volumes", "China / Europe activity data"],
        "counter": "Where could regional divergence break the thesis?",
    },
    "inflation": {
        "lean": "Define the path and persistence of inflation",
        "signals": ["Core services momentum", "Wages and productivity", "Goods, housing, and supply chains"],
        "counter": "Which inflation component could surprise you most?",
    },
    "fed": {
        "lean": "Set your policy-path view versus pricing",
        "signals": ["Labor-market rebalancing", "Inflation progress", "OIS / futures pricing"],
        "counter": "What would force the Fed away from your path?",
    },
    "term_premium": {
        "lean": "Define the direction of term premium",
        "signals": ["Treasury supply and demand", "Rate volatility", "Fiscal and inflation risk"],
        "counter": "What could compress term premium despite the risks?",
    },
    "credit": {
        "lean": "Set the spread and default-cycle view",
        "signals": ["Lending standards", "Defaults and downgrades", "Spreads, dispersion, and issuance"],
        "counter": "What breaks the benign or stressed credit case?",
    },
    "usd": {
        "lean": "Define the dollar regime and horizon",
        "signals": ["Relative growth", "Rate differentials", "Risk appetite and funding stress"],
        "counter": "What would reverse the dollar regime?",
    },
}

_CSS_INJECTED = False


def _inject_css():
    global _CSS_INJECTED
    if _CSS_INJECTED:
        return
    _CSS_INJECTED = True
    ui.add_head_html('''<style id="mq-macro-views-css">
        .mv-grid-header {
            display: grid;
            grid-template-columns: 96px minmax(140px, 180px) minmax(220px, 1fr) 62px 72px 18px;
            gap: 0 0.7rem;
            padding: 0 0.75rem 0.35rem;
            align-items: center;
        }
        .mv-grid-row {
            display: grid;
            grid-template-columns: 96px minmax(140px, 180px) minmax(220px, 1fr) 62px 72px 18px;
            gap: 0 0.7rem;
            padding: 0.5rem 0.75rem;
            align-items: center;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            cursor: pointer;
            transition: border-color 0.12s, background 0.12s;
            min-height: 58px;
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
        .mv-summary {
            display:flex; align-items:center; justify-content:space-between; gap:1rem;
            width:100%; padding:1rem 1.1rem; margin:0.25rem 0 1rem;
            background:linear-gradient(135deg,var(--bg-card),var(--accent-glow));
            border:1px solid var(--border-strong); border-radius:7px;
        }
        .mv-summary-title { font-size:0.95rem; font-weight:700; color:var(--text-primary); }
        .mv-summary-copy { font-size:0.72rem; color:var(--text-muted); margin-top:0.2rem; }
        .mv-progress-track {
            width:150px; height:6px; background:var(--border); border-radius:999px;
            overflow:hidden; margin-top:0.35rem;
        }
        .mv-progress-fill { height:100%; background:var(--accent); border-radius:999px; }
        .mv-empty-lean { color:var(--accent) !important; opacity:0.8; }
        .mv-choice-grid {
            display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0.4rem; width:100%;
        }
        .mv-choice-button {
            min-height:38px !important; padding:0.35rem 0.45rem !important;
            background:var(--bg-input) !important; color:var(--text-muted) !important;
            border:1px solid var(--border) !important; border-radius:6px !important;
            box-shadow:none !important; font-family:var(--font-ui) !important;
            font-size:0.74rem !important; font-weight:600 !important;
            text-transform:none !important;
        }
        .mv-choice-button:hover { border-color:var(--accent) !important; color:var(--text-primary) !important; }
        .mv-choice-button.is-active {
            color:var(--accent) !important; border-color:var(--accent) !important;
            background:var(--accent-glow) !important;
        }
        @media (max-width: 820px) {
            .mv-grid-header { display:none; }
            .mv-grid-row {
                grid-template-columns:minmax(0,1fr) auto;
                grid-template-areas:
                    "name direction"
                    "lean lean"
                    "conviction updated";
                row-gap:0.4rem; column-gap:0.75rem; padding:0.75rem 0.85rem;
            }
            .mv-direction { grid-area:direction; }
            .mv-name { grid-area:name; }
            .mv-lean { grid-area:lean; }
            .mv-conviction { grid-area:conviction; }
            .mv-updated { grid-area:updated; justify-self:end; }
            .mv-conviction::before {
                content:'CONVICTION'; color:var(--text-faint); font-size:0.55rem;
                letter-spacing:0.1em; margin-right:0.55rem; vertical-align:middle;
            }
            .mv-updated::before {
                content:'UPDATED  '; color:var(--text-faint); font-size:0.55rem;
                letter-spacing:0.1em;
            }
            .mv-arrow { display:none !important; }
            .mv-summary { align-items:flex-start; flex-direction:column; }
            .mv-progress-track { width:min(280px,75vw); }
        }
    </style>''')


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


def _choice_control(options: list[str], current_value, on_select) -> None:
    container = ui.element("div").classes("mv-choice-grid")

    def choose(value: str):
        on_select(value)
        render()

    def render():
        container.clear()
        with container:
            for option in options:
                button = ui.button(option, on_click=lambda _, value=option: choose(value)).classes(
                    "mv-choice-button"
                )
                if option == current_value():
                    button.classes(add="is-active")

    render()


def _build_row_contents(view: MacroView):
    dc = DIRECTION_COLORS.get(view.direction, DIRECTION_COLORS["No View"])
    d = days_since(view.last_touched)
    s_label = "not set" if d is None else ("today" if d == 0 else f"{d}d ago")
    s_color = staleness_color(d)

    direction_label = "SET VIEW" if view.direction == "No View" else view.direction
    ui.element("span").classes("mv-direction").style(
        f"background:{dc['bg']};color:{dc['text']};padding:2px 7px;border-radius:4px;"
        f"font-size:0.67rem;font-weight:700;letter-spacing:0.05em;"
        f"border:1px solid {dc['text']}33;white-space:nowrap;text-align:center;"
    ).text = direction_label

    ui.label(view.name).classes("mv-name").style(
        "font-weight:600;font-size:0.85rem;white-space:nowrap;"
        "overflow:hidden;text-overflow:ellipsis;"
    )

    if view.lean:
        ui.label(view.lean).classes("mv-lean").style(
            "font-style:italic;color:var(--text-muted);font-size:0.78rem;"
            "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
        )
    else:
        prompt = STARTER_GUIDANCE.get(view.id, {}).get("lean", "Add your thesis")
        ui.label(f"{prompt} →").classes("mv-lean mv-empty-lean").style("font-size:0.76rem;")

    ui.html(_conviction_bars_html(view.conviction)).classes("mv-conviction")

    ui.label(s_label).classes("mv-updated").style(
        f"color:{s_color};font-size:0.71rem;white-space:nowrap;text-align:right;"
    )

    ui.label("›").classes("mv-arrow").style(
        "color:var(--text-faint);font-size:1rem;text-align:center;line-height:1;"
    )


def render_macro_views(state: AppState, save_indicator):
    _inject_css()
    summary_controls = {}

    def save():
        save_state(state)
        save_indicator()
        completed_now = sum(
            1 for item in state.macro_views
            if item.direction != "No View" and bool(item.lean.strip())
        )
        total_now = len(state.macro_views) or 1
        if summary_controls:
            summary_controls["count"].set_text(f"{completed_now} / {total_now} views set")
            summary_controls["fill"].style(f"width:{round(completed_now / total_now * 100)}%;")

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
            _render_drawer(view, state, save, drawer, row_containers)
        drawer.open()

    completed = sum(
        1 for view in state.macro_views
        if view.direction != "No View" and bool(view.lean.strip())
    )
    total = len(state.macro_views) or 1
    pct = round(completed / total * 100)
    with ui.element("div").classes("mv-summary"):
        with ui.element("div"):
            ui.label("MACRO VIEW INVENTORY").classes("mv-summary-title")
            ui.label(
                "Click a theme to set the thesis, evidence, conviction, and strongest counterargument."
            ).classes("mv-summary-copy")
        with ui.element("div").style("flex-shrink:0;"):
            summary_controls["count"] = ui.label(f"{completed} / {total} views set").style(
                "font-size:0.72rem;font-weight:700;color:var(--accent);"
            )
            with ui.element("div").classes("mv-progress-track"):
                summary_controls["fill"] = ui.element("div").classes("mv-progress-fill").style(f"width:{pct}%;")

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
    _choice_control(
        ["Bearish", "Neutral", "Bullish", "No View"],
        lambda: view.direction,
        lambda value: (setattr(view, "direction", value), update_and_save()),
    )

    # ── Conviction ────────────────────────────────────────────────────────────
    ui.label("CONVICTION").classes("field-label").style("margin-top:0.75rem;")
    _choice_control(
        ["Low", "Medium", "High", "—"],
        lambda: view.conviction,
        lambda value: (setattr(view, "conviction", value), update_and_save()),
    )

    # ── Lean ──────────────────────────────────────────────────────────────────
    ui.label("DIRECTIONAL LEAN").classes("field-label").style("margin-top:0.75rem;")
    lean_input = ui.textarea(
        value=view.lean,
        placeholder=STARTER_GUIDANCE.get(view.id, {}).get(
            "lean", "One sentence — direction, magnitude, where uncertainty sits…"
        )
    ).classes("w-full dark-input")
    lean_input.on("blur", lambda _, v=view, li=lean_input: (
        setattr(v, "lean", li.value), update_and_save()
    ))

    # ── Signals ───────────────────────────────────────────────────────────────
    ui.label("THREE SUPPORTING SIGNALS").classes("field-label").style("margin-top:0.75rem;")
    signal_inputs = []
    for i in range(3):
        signal_prompts = STARTER_GUIDANCE.get(view.id, {}).get("signals", [])
        si = ui.input(
            value=view.signals[i] if i < len(view.signals) else "",
            placeholder=signal_prompts[i] if i < len(signal_prompts) else "Data point, model output, or market behavior…"
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
        placeholder=STARTER_GUIDANCE.get(view.id, {}).get(
            "counter", "Best argument against your own view…"
        )
    ).classes("w-full dark-input")
    counter_input.on("blur", lambda _, v=view, ci=counter_input: (
        setattr(v, "counter", ci.value), update_and_save()
    ))
