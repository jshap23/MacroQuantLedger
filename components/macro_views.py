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
        .mv-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-left: 3px solid var(--border);
            border-radius: 8px;
            padding: 0.9rem 1.1rem 0.85rem;
            transition: border-color 0.15s, background 0.15s;
        }
        .mv-card:hover {
            border-color: var(--border-strong);
            background: var(--bg-hover);
        }
        .mv-card-header {
            display: flex; align-items: center; gap: 0.55rem;
        }
        .mv-card-num {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.66rem; font-weight: 700;
            color: var(--text-faint); letter-spacing: 0.06em;
            flex-shrink: 0; line-height: 1; min-width: 1.3rem;
        }
        .mv-card-name {
            font-weight: 700; font-size: 1.02rem; color: var(--text-primary);
            letter-spacing: -0.005em; line-height: 1.25;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            flex: 1; min-width: 0;
        }
        .mv-card-staleness {
            font-size: 0.66rem; white-space: nowrap; flex-shrink: 0;
            font-family: 'IBM Plex Mono', monospace; font-weight: 600;
        }
        .mv-details-btn {
            background: transparent !important; color: var(--text-muted) !important;
            border: 1px solid var(--border) !important; border-radius: 5px !important;
            box-shadow: none !important; font-family: var(--font-ui) !important;
            font-size: 0.66rem !important; font-weight: 600 !important;
            padding: 0.18rem 0.55rem !important; min-height: unset !important;
            text-transform: none !important; flex-shrink: 0; cursor: pointer;
            transition: border-color 0.12s, color 0.12s;
        }
        .mv-details-btn:hover {
            border-color: var(--accent) !important; color: var(--accent) !important;
        }
        .mv-thesis-line {
            font-size: 0.82rem; color: var(--text-muted);
            padding: 0.4rem 0 0.4rem 0.05rem;
            cursor: pointer; overflow: hidden;
            display: flex; align-items: center; gap: 0.4rem; min-height: 1.7rem;
            transition: color 0.12s;
        }
        .mv-thesis-line:hover { color: var(--text-primary); }
        .mv-thesis-text {
            flex: 1; min-width: 0; overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap;
        }
        .mv-thesis-empty { color: var(--accent); opacity: 0.75; }
        .mv-thesis-edit-tag {
            font-size: 0.56rem; color: var(--text-faint); letter-spacing: 0.1em;
            font-weight: 700; flex-shrink: 0;
            font-family: 'IBM Plex Mono', monospace;
            transition: color 0.12s;
        }
        .mv-thesis-line:hover .mv-thesis-edit-tag { color: var(--accent); }
        .mv-chip-row {
            display: flex; align-items: center; gap: 0.3rem;
            flex-wrap: wrap; margin-top: 0.35rem;
        }
        .mv-chip-row + .mv-chip-row { margin-top: 0.3rem; }
        .mv-chip-label {
            font-size: 0.55rem; font-weight: 700; color: var(--text-faint);
            letter-spacing: 0.14em; font-family: 'IBM Plex Mono', monospace;
            margin-right: 0.1rem; flex-shrink: 0; min-width: 4.6rem;
        }
        .mv-chip {
            padding: 0.16rem 0.6rem !important; border-radius: 999px !important;
            font-size: 0.68rem !important; font-weight: 600 !important;
            font-family: var(--font-ui) !important;
            background: transparent !important; color: var(--text-faint) !important;
            border: 1px solid var(--border) !important; box-shadow: none !important;
            cursor: pointer; transition: border-color 0.12s, color 0.12s, background 0.12s;
            white-space: nowrap; user-select: none; text-transform: none !important;
            min-height: unset !important; line-height: 1.4;
        }
        .mv-chip:hover {
            border-color: var(--border-strong) !important;
            color: var(--text-muted) !important;
        }
        .mv-chip.is-active {
            color: var(--accent) !important; border-color: var(--accent) !important;
            background: var(--accent-glow) !important;
        }
        .mv-drawer-card {
            width: min(460px, 95vw); height: 100vh;
            background: var(--bg-card); color: var(--text-primary);
            border-left: 1px solid var(--border-strong);
            border-radius: 0; padding: 0; margin: 0; overflow-y: auto;
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
        @media (max-width: 640px) {
            .mv-card { padding: 0.75rem 0.85rem 0.7rem; }
            .mv-card-name { font-size: 0.95rem; }
            .mv-chip-label { display: none; }
            .mv-summary { align-items:flex-start; flex-direction:column; }
            .mv-progress-track { width:min(280px,75vw); }
        }
    </style>''')


def _conviction_bars_html(conviction: str) -> str:
    """Render conviction bars as inline HTML. Preserved for backward compatibility."""
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


# ── Card section builders ──────────────────────────────────────────────

def _build_card_header(view: MacroView, index: int, open_drawer_fn):
    d = days_since(view.last_touched)
    s_label = "not set" if d is None else ("today" if d == 0 else f"{d}d ago")
    s_color = staleness_color(d)

    ui.label(f"{index:02d}").classes("mv-card-num")
    ui.label(view.name).classes("mv-card-name")
    ui.label(s_label).classes("mv-card-staleness").style(f"color:{s_color};")
    ui.button("Details", on_click=lambda _, v=view: open_drawer_fn(v)).classes("mv-details-btn")


def _build_thesis_summary(view: MacroView, on_edit):
    line = ui.element("div").classes("mv-thesis-line")
    if view.lean:
        ui.label(view.lean).classes("mv-thesis-text")
    else:
        prompt = STARTER_GUIDANCE.get(view.id, {}).get("lean", "Add your thesis")
        line.classes(add="mv-thesis-empty")
        ui.label(f"{prompt} \u2192").classes("mv-thesis-text")
    ui.label("EDIT").classes("mv-thesis-edit-tag")
    line.on("click", lambda _: on_edit())


def _build_thesis_editor(view: MacroView, save, on_done):
    ta = ui.textarea(
        value=view.lean,
        placeholder=STARTER_GUIDANCE.get(view.id, {}).get(
            "lean", "One sentence \u2014 direction, magnitude, where uncertainty sits\u2026"
        ),
    ).classes("w-full dark-input").style("margin-top:0.2rem; min-height:64px;")

    def on_blur(_):
        view.lean = ta.value
        view.last_touched = datetime.now(tz=timezone.utc)
        save()
        on_done()

    ta.on("blur", on_blur)


def _build_direction_chips(view: MacroView, on_select):
    ui.label("DIRECTION").classes("mv-chip-label")
    for option in ["Bearish", "Neutral", "Bullish", "No View"]:
        chip = ui.button(option, on_click=lambda _, v=option: on_select(v)).classes("mv-chip")
        if option == view.direction:
            dc = DIRECTION_COLORS.get(option, DIRECTION_COLORS["No View"])
            chip.classes(add="is-active")
            if option == "No View":
                chip.style(
                    "color:var(--text-muted) !important;"
                    "border-color:var(--border-strong) !important;"
                    "background:var(--bg-hover) !important;"
                )
            else:
                chip.style(
                    f"color:{dc['text']} !important;"
                    f"border-color:{dc['text']} !important;"
                    f"background:{dc['text']}18 !important;"
                )


def _build_conviction_chips(view: MacroView, on_select):
    ui.label("CONVICTION").classes("mv-chip-label")
    for option in ["Low", "Medium", "High", "\u2014"]:
        chip = ui.button(option, on_click=lambda _, v=option: on_select(v)).classes("mv-chip")
        if option == view.conviction:
            chip.classes(add="is-active")


# ── Card renderer ──────────────────────────────────────────────────────

def _render_card(view: MacroView, save, open_drawer_fn, index: int) -> dict:
    """Render one inline quick-set card. Returns refresh helpers for external callers."""
    dc = DIRECTION_COLORS.get(view.direction, DIRECTION_COLORS["No View"])
    card = ui.element("div").classes("mv-card").style(
        f"border-left-color:{dc['text']};"
    )
    with card:
        header_el = ui.element("div").classes("mv-card-header")
        thesis_el = ui.element("div")
        dir_el = ui.element("div").classes("mv-chip-row")
        conv_el = ui.element("div").classes("mv-chip-row")

    card_state = {"editing_thesis": False}

    def refresh_accent():
        dc = DIRECTION_COLORS.get(view.direction, DIRECTION_COLORS["No View"])
        card.style(f"border-left-color:{dc['text']};")

    def refresh_header():
        header_el.clear()
        with header_el:
            _build_card_header(view, index, open_drawer_fn)

    def refresh_thesis():
        thesis_el.clear()
        with thesis_el:
            if card_state["editing_thesis"]:
                _build_thesis_editor(view, save, _on_thesis_done)
            else:
                _build_thesis_summary(view, _on_thesis_edit)

    def refresh_direction():
        dir_el.clear()
        with dir_el:
            _build_direction_chips(view, _on_dir_select)

    def refresh_conviction():
        conv_el.clear()
        with conv_el:
            _build_conviction_chips(view, _on_conv_select)

    def _on_thesis_edit():
        card_state["editing_thesis"] = True
        refresh_thesis()

    def _on_thesis_done():
        card_state["editing_thesis"] = False
        refresh_thesis()
        refresh_header()

    def _on_dir_select(value):
        view.direction = value
        view.last_touched = datetime.now(tz=timezone.utc)
        save()
        refresh_accent()
        refresh_header()
        refresh_direction()

    def _on_conv_select(value):
        view.conviction = value
        view.last_touched = datetime.now(tz=timezone.utc)
        save()
        refresh_header()
        refresh_conviction()

    refresh_header()
    refresh_thesis()
    refresh_direction()
    refresh_conviction()

    return {"refresh_header": refresh_header}


# ── Drawer (signals + counter only) ────────────────────────────────────

def _render_drawer(view: MacroView, save, dialog, refresh_header):
    def update_and_save():
        view.last_touched = datetime.now(tz=timezone.utc)
        save()
        if refresh_header:
            refresh_header()

    with ui.row().style(
        "width:100%;align-items:center;justify-content:space-between;"
        "margin-bottom:1.5rem;border-bottom:1px solid var(--border);padding-bottom:1rem;"
    ):
        ui.label(view.name).style(
            "font-size:1rem;font-weight:700;color:var(--accent);letter-spacing:0.08em;"
        )
        ui.button("\u2715", on_click=dialog.close).style(
            "background:transparent;color:var(--text-muted);box-shadow:none;"
            "min-width:unset;padding:0 0.5rem;font-size:1rem;line-height:1;"
        )

    ui.label("THREE SUPPORTING SIGNALS").classes("field-label")
    signal_inputs = []
    for i in range(3):
        signal_prompts = STARTER_GUIDANCE.get(view.id, {}).get("signals", [])
        si = ui.input(
            value=view.signals[i] if i < len(view.signals) else "",
            placeholder=signal_prompts[i] if i < len(signal_prompts)
            else "Data point, model output, or market behavior\u2026"
        ).classes("w-full dark-input").style("margin-bottom:4px;")
        signal_inputs.append(si)

    def save_signals(v=view, sis=signal_inputs):
        v.signals = [s.value for s in sis]
        update_and_save()

    for si in signal_inputs:
        si.on("blur", lambda _, fn=save_signals: fn())

    ui.label("THE COUNTER").classes("field-label").style("margin-top:0.75rem;")
    counter_input = ui.textarea(
        value=view.counter,
        placeholder=STARTER_GUIDANCE.get(view.id, {}).get(
            "counter", "Best argument against your own view\u2026"
        )
    ).classes("w-full dark-input")
    counter_input.on("blur", lambda _, v=view, ci=counter_input: (
        setattr(v, "counter", ci.value), update_and_save()
    ))


# ── Public entry point ─────────────────────────────────────────────────

def render_macro_views(state: AppState, save_indicator):
    _inject_css()
    summary_controls = {}
    card_refreshers: dict = {}

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

    # ── Side drawer (Quasar right-position dialog) ─────────────────────────────
    with ui.dialog().props('position="right" full-height').style(
        "font-family:'IBM Plex Mono',monospace;"
    ) as drawer:
        with ui.element("div").classes("mv-drawer-card"):
            drawer_body = ui.column().style("width:100%;gap:0;padding:1.25rem 1.25rem 2rem;")

    def open_drawer(view: MacroView):
        drawer_body.clear()
        with drawer_body:
            refresher = card_refreshers.get(view.id, {})
            _render_drawer(view, save, drawer, refresher.get("refresh_header"))
        drawer.open()

    # ── Summary banner ─────────────────────────────────────────────────────────
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
                "Set direction and conviction inline, edit the thesis, "
                "then open Details for signals and the counter."
            ).classes("mv-summary-copy")
        with ui.element("div").style("flex-shrink:0;"):
            summary_controls["count"] = ui.label(f"{completed} / {total} views set").style(
                "font-size:0.72rem;font-weight:700;color:var(--accent);"
            )
            with ui.element("div").classes("mv-progress-track"):
                summary_controls["fill"] = ui.element("div").classes("mv-progress-fill").style(f"width:{pct}%;")

    # ── Cards ──────────────────────────────────────────────────────────────────
    with ui.column().style("width:100%;gap:0.75rem;"):
        for idx, view in enumerate(state.macro_views, 1):
            refresher = _render_card(view, save, open_drawer, idx)
            card_refreshers[view.id] = refresher

    # ── Notes ──────────────────────────────────────────────────────────────────
    ui.label("NOTES").classes("section-header").style("margin-top:2rem;")
    notes_area = ui.textarea(
        placeholder="Cross-cutting themes, half-formed ideas, anything that doesn't fit neatly into a single variable\u2026"
    ).classes("w-full dark-input").style("min-height:120px;")
    notes_area.value = state.macro_notes

    def on_notes_blur():
        state.macro_notes = notes_area.value
        save()

    notes_area.on("blur", lambda _: on_notes_blur())
