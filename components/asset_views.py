from __future__ import annotations
from datetime import datetime, timezone
from nicegui import ui
from models.schema import AppState, AssetView
from storage.persistence import save_state
from components.status_bar import days_since, staleness_color
from components.macro_views import CONVICTION_BARS, _conviction_bars_html

# Score system: 1 (lowest/red) → 5 (highest/green), — = no view
SCORE_OPTIONS = ["—", "1", "2", "3", "4", "5"]
SCORE_COLORS = {
    "5": {"bg": "#14532d", "text": "#4ade80", "dot": "#4ade80"},
    "4": {"bg": "#166534", "text": "#86efac", "dot": "#86efac"},
    "3": {"bg": "#1f2937", "text": "#9ca3af", "dot": "#9ca3af"},
    "2": {"bg": "#7c2d12", "text": "#fb923c", "dot": "#fb923c"},
    "1": {"bg": "#7f1d1d", "text": "#f87171", "dot": "#f87171"},
    "—": {"bg": "#1e1e24", "text": "#44445a", "dot": "#44445a"},
}


def render_asset_views(state: AppState, save_indicator):
    def save():
        save_state(state)
        save_indicator()

    by_group = {
        "l1":           [v for v in state.asset_views if v.group == "l1"],
        "equities":     [v for v in state.asset_views if v.group == "equities"],
        "fixed_income": [v for v in state.asset_views if v.group == "fixed_income"],
    }

    with ui.column().classes("w-full").style("gap:0;"):

        # ── Level 1: Cross-asset ──────────────────────────────────────────────
        ui.label("LEVEL 1 — CROSS-ASSET").classes("section-header")
        for av in by_group["l1"]:
            _l1_row(av, save)

        # ── Level 2: two-column grid ──────────────────────────────────────────
        ui.label("LEVEL 2 — INTRA-ASSET").classes("section-header").style("margin-top:1.5rem;")

        with ui.row().classes("w-full").style("gap:1rem; align-items:flex-start; flex-wrap:wrap;"):
            with ui.column().style("flex:1; min-width:360px; gap:0;"):
                _group_header("EQUITIES")
                for av in by_group["equities"]:
                    _l2_row(av, save)

            with ui.column().style("flex:1; min-width:360px; gap:0;"):
                _group_header("FIXED INCOME")
                for av in by_group["fixed_income"]:
                    _l2_row(av, save)

        # ── Deep Dive Commentary ──────────────────────────────────────────────
        _render_commentary(state, save)


def _group_header(label: str):
    ui.label(label).style(
        "font-size:0.62rem; font-weight:700; color:var(--text-muted); "
        "letter-spacing:0.15em; padding:0.4rem 0.75rem 0.3rem; "
        "border-bottom:1px solid var(--border); margin-bottom:2px; width:100%;"
    )


def _score_badge_html(score: str) -> str:
    sc = SCORE_COLORS.get(score, SCORE_COLORS["—"])
    return (
        f'<span style="background:{sc["bg"]}; color:{sc["text"]}; '
        f'border:1px solid {sc["text"]}33; border-radius:4px; '
        f'padding:2px 9px; font-size:0.78rem; font-weight:700; '
        f'letter-spacing:0.05em; white-space:nowrap;">{score}</span>'
    )


def _score_dot_style(score: str) -> str:
    color = SCORE_COLORS.get(score, SCORE_COLORS["—"])["dot"]
    return (
        f"width:9px; height:9px; border-radius:50%; background:{color}; "
        f"display:inline-block; flex-shrink:0;"
    )


def _l1_row(av: AssetView, save):
    sc = SCORE_COLORS.get(av.direction, SCORE_COLORS["—"])

    with ui.row().classes("w-full asset-row-l1").style("align-items:center; gap:0.75rem;"):
        # Score badge (dynamic)
        badge = ui.html(_score_badge_html(av.direction)).style("flex-shrink:0;")

        ui.label(av.name).style(
            "font-weight:700; font-size:0.95rem; min-width:140px; flex-shrink:0;"
        )

        ui.select(
            SCORE_OPTIONS,
            value=av.direction,
            on_change=lambda e, a=av, b=badge: (
                setattr(a, "direction", e.value),
                b.set_content(_score_badge_html(e.value)),
                _touch_save(a, None, None, save),
            )
        ).classes("dark-input").style("width:90px; flex-shrink:0;")

        _conviction_cycle_btn(av, save)

        note_in = ui.input(
            value=av.note,
            placeholder="Cross-asset thesis in one line…"
        ).classes("dark-input").style("flex:1; min-width:0;")
        note_in.on("blur", lambda _, a=av, ni=note_in: _touch_save(a, "note", ni.value, save))

        _staleness_label(av)


def _l2_row(av: AssetView, save):
    with ui.row().classes("w-full asset-row-l2").style("align-items:center; gap:0.5rem;"):
        # Score dot (dynamic)
        dot = ui.element("span").style(_score_dot_style(av.direction))

        ui.label(av.name).style(
            "font-size:0.85rem; min-width:130px; flex-shrink:0; color:var(--text-primary);"
        )

        ui.select(
            SCORE_OPTIONS,
            value=av.direction,
            on_change=lambda e, a=av, d=dot: (
                setattr(a, "direction", e.value),
                d.style(_score_dot_style(e.value)),
                _touch_save(a, None, None, save),
            )
        ).classes("dark-input").style("width:80px; flex-shrink:0;")

        _conviction_cycle_btn(av, save)

        note_in = ui.input(
            value=av.note,
            placeholder="One-line thesis…"
        ).classes("dark-input").style("flex:1; min-width:0; font-size:0.82rem;")
        note_in.on("blur", lambda _, a=av, ni=note_in: _touch_save(a, "note", ni.value, save))

        _staleness_label(av, compact=True)


def _conviction_cycle_btn(av: AssetView, save):
    cycle = ["—", "Low", "Medium", "High"]
    btn = ui.html(_conviction_bars_html(av.conviction)).style(
        "cursor:pointer; padding:4px 6px; border-radius:4px; "
        "border:1px solid var(--border); background:var(--bg-input); "
        "flex-shrink:0; display:inline-flex; align-items:center;"
    )

    def on_click(e, a=av, b=btn):
        idx = cycle.index(a.conviction) if a.conviction in cycle else 0
        a.conviction = cycle[(idx + 1) % len(cycle)]
        b.set_content(_conviction_bars_html(a.conviction))
        _touch_save(a, None, None, save)

    btn.on("click", on_click)


def _staleness_label(av: AssetView, compact: bool = False):
    d = days_since(av.last_touched)
    label = "—" if d is None else ("today" if d == 0 else f"{d}d")
    color = staleness_color(d)
    size = "0.7rem" if compact else "0.75rem"
    width = "38px" if compact else "52px"
    ui.label(label).style(
        f"color:{color}; font-size:{size}; white-space:nowrap; "
        f"flex-shrink:0; min-width:{width}; text-align:right;"
    )


def _render_commentary(state: AppState, save):
    ui.label("DEEP DIVE").classes("section-header").style("margin-top:2rem;")

    all_views = state.asset_views
    names = [av.name for av in all_views]
    selected = {"av": all_views[0] if all_views else None}
    text_ref = {"ta": None}

    with ui.column().classes("w-full").style(
        "background:var(--bg-card); border:1px solid var(--border); "
        "border-radius:6px; padding:1rem; gap:0.75rem;"
    ):
        # Selector row — at the top
        with ui.row().style("align-items:center; gap:1rem;"):
            ui.label("ASSET CLASS").style(
                "font-size:0.62rem; font-weight:700; color:var(--text-muted); "
                "letter-spacing:0.12em; flex-shrink:0;"
            )

            def on_select(e):
                name_val = getattr(e, "value", None) or e.args
                # Save current before switching
                if selected["av"] is not None and text_ref["ta"] is not None:
                    selected["av"].commentary = text_ref["ta"].value
                    selected["av"].last_touched = datetime.now(tz=timezone.utc)
                    save()
                # Load new
                av = next((v for v in all_views if v.name == name_val), None)
                if av and text_ref["ta"] is not None:
                    selected["av"] = av
                    text_ref["ta"].set_value(av.commentary)

            ui.select(
                names,
                value=names[0] if names else None,
                on_change=on_select,
            ).classes("dark-input").style("width:220px;")

        # Textarea — below the selector
        ta = ui.textarea(
            placeholder="Write as much as you want — thesis, risks, catalysts, positioning rationale…"
        ).classes("w-full dark-input").style("min-height:200px; font-size:0.88rem;")
        ta.value = selected["av"].commentary if selected["av"] else ""
        text_ref["ta"] = ta

        def on_blur():
            if selected["av"] is not None:
                selected["av"].commentary = ta.value
                selected["av"].last_touched = datetime.now(tz=timezone.utc)
                save()

        ta.on("blur", lambda _: on_blur())


def _touch_save(av: AssetView, field: str | None, value, save):
    if field is not None:
        setattr(av, field, value)
    av.last_touched = datetime.now(tz=timezone.utc)
    save()
