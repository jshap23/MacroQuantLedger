"""Briefing tab — spoken-style talking points from AppState + optional FRED data."""
from __future__ import annotations
import asyncio
from nicegui import ui, run
from models.schema import AppState
from components.macro_views import DIRECTION_COLORS, CONVICTION_BARS, _conviction_bars_html
from components.asset_views import SCORE_COLORS, _load_tenure_data
from components.status_bar import days_since, staleness_color, staleness_label
from services.talking_points import (
    MACRO_FRED_MAP, VERBAL_SCORE, macro_prose, fred_snippet, asset_verbal
)
from services.llm_polish import available as llm_available, polish as llm_polish, get_cached

_CSS_INJECTED = False


def _inject_css():
    global _CSS_INJECTED
    if _CSS_INJECTED:
        return
    _CSS_INJECTED = True
    ui.add_css("""
        .brief-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            margin-bottom: 0.75rem;
            overflow: hidden;
        }
        .brief-card-header {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            padding: 0.55rem 0.85rem;
            border-bottom: 1px solid var(--border);
        }
        .brief-card-body {
            padding: 0.85rem;
        }
        .brief-prose {
            font-size: 0.88rem;
            line-height: 1.65;
            color: var(--text-primary);
            font-family: 'IBM Plex Mono', monospace;
            white-space: pre-wrap;
        }
        .brief-fred-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.3rem 1.1rem;
            margin-top: 0.6rem;
            padding: 0.5rem 0.7rem;
            background: var(--bg-primary);
            border-radius: 4px;
            border: 1px solid var(--border);
        }
        .brief-fred-item {
            font-size: 0.76rem;
            color: var(--text-muted);
            font-family: 'IBM Plex Mono', monospace;
            white-space: nowrap;
        }
        .brief-polished-block {
            margin-top: 0.7rem;
            padding: 0.65rem 0.8rem;
            background: var(--accent-dim);
            border: 1px solid var(--accent);
            border-radius: 4px;
            font-size: 0.88rem;
            line-height: 1.65;
            color: var(--text-primary);
            font-family: 'IBM Plex Mono', monospace;
        }
        .brief-polish-label {
            font-size: 0.6rem;
            font-weight: 700;
            color: var(--accent);
            letter-spacing: 0.14em;
            margin-bottom: 0.3rem;
            font-family: 'IBM Plex Mono', monospace;
        }
        .brief-polish-btn {
            background: transparent !important;
            border: 1px solid var(--border-strong) !important;
            color: var(--text-muted) !important;
            font-family: 'IBM Plex Mono', monospace !important;
            font-size: 0.72rem !important;
            border-radius: 4px !important;
            box-shadow: none !important;
            padding: 0 0.75rem !important;
            min-height: 1.8rem !important;
        }
        .brief-polish-btn:hover {
            border-color: var(--accent) !important;
            color: var(--accent) !important;
        }
        .brief-opener {
            background: var(--bg-card);
            border: 1px solid var(--border-strong);
            border-radius: 6px;
            padding: 1rem 1.1rem;
            margin-bottom: 1.5rem;
        }
        .brief-asset-row {
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            padding: 0.35rem 0;
            border-bottom: 1px solid var(--border);
            font-family: 'IBM Plex Mono', monospace;
        }
        .brief-asset-row:last-child { border-bottom: none; }
        .brief-no-view {
            color: var(--text-faint);
            font-size: 0.8rem;
            font-style: italic;
            font-family: 'IBM Plex Mono', monospace;
        }
    """)


# ── Opener section ─────────────────────────────────────────────────────────────

def _render_opener(state: AppState):
    top = state.briefing.top_of_mind.strip() if state.briefing else ""
    synthesis = ""
    if state.reconciliations:
        s = state.reconciliations[0].synthesis
        if s and s.strip():
            synthesis = s.strip()

    if not top and not synthesis:
        with ui.element("div").classes("brief-opener"):
            ui.label("No opener set — fill in Top of Mind on the Macro Views tab.").style(
                "color:var(--text-faint); font-size:0.8rem; font-style:italic; "
                "font-family:'IBM Plex Mono',monospace;"
            )
        return

    with ui.element("div").classes("brief-opener"):
        if top:
            ui.label("OPENER").style(
                "font-size:0.6rem; font-weight:700; color:var(--accent); "
                "letter-spacing:0.14em; margin-bottom:0.4rem; "
                "font-family:'IBM Plex Mono',monospace;"
            )
            ui.label(top).style(
                "font-size:0.9rem; line-height:1.6; color:var(--text-primary); "
                "font-family:'IBM Plex Mono',monospace; white-space:pre-wrap;"
            )
        if synthesis:
            ui.label("LAST SYNTHESIS").style(
                "font-size:0.6rem; font-weight:700; color:var(--text-muted); "
                "letter-spacing:0.14em; margin-top:0.75rem; margin-bottom:0.25rem; "
                "font-family:'IBM Plex Mono',monospace;"
            )
            ui.label(f'"{synthesis}"').style(
                "font-size:0.82rem; color:var(--text-muted); font-style:italic; "
                "font-family:'IBM Plex Mono',monospace;"
            )


# ── Single macro card ──────────────────────────────────────────────────────────

def _render_macro_card(view, fred_index: dict, has_llm: bool):
    dc = DIRECTION_COLORS.get(view.direction, DIRECTION_COLORS["No View"])
    d = days_since(view.last_touched)
    s_color = staleness_color(d)
    s_label = staleness_label(d)

    prose = macro_prose(view)
    is_empty = (
        view.direction == "No View"
        and not view.lean.strip()
        and not any(s.strip() for s in view.signals)
        and not view.counter.strip()
    )

    with ui.element("div").classes("brief-card").style(
        f"border-left: 3px solid {dc['text']}44;"
    ):
        # ── Header ────────────────────────────────────────────────────────────
        with ui.element("div").classes("brief-card-header").style(
            f"background:{dc['bg']}22;"
        ):
            ui.element("span").style(
                f"background:{dc['bg']}; color:{dc['text']}; padding:2px 7px; "
                f"border-radius:4px; font-size:0.67rem; font-weight:700; "
                f"letter-spacing:0.05em; border:1px solid {dc['text']}33; "
                f"white-space:nowrap; flex-shrink:0;"
            ).text = view.direction

            ui.label(view.name).style(
                "font-weight:700; font-size:0.88rem; flex:1; "
                "font-family:'IBM Plex Mono',monospace;"
            )

            ui.html(_conviction_bars_html(view.conviction)).style("flex-shrink:0;")

            ui.label(s_label).style(
                f"color:{s_color}; font-size:0.7rem; white-space:nowrap; "
                f"flex-shrink:0; font-family:'IBM Plex Mono',monospace;"
            )

        # ── Body ──────────────────────────────────────────────────────────────
        with ui.element("div").classes("brief-card-body"):
            if is_empty:
                ui.label("No view set — open the drawer on Macro Views to fill in your lean and signals.").classes("brief-no-view")
                return

            # Template prose
            ui.element("div").classes("brief-prose").text = prose

            # FRED data line
            fred_ids = MACRO_FRED_MAP.get(view.id, [])
            snippets = [fred_snippet(fid, fred_index) for fid in fred_ids]
            snippets = [s for s in snippets if s]
            if snippets:
                with ui.element("div").classes("brief-fred-row"):
                    for snip in snippets:
                        ui.label(snip).classes("brief-fred-item")

            # LLM polish
            if not has_llm:
                return

            full_text = prose
            if snippets:
                full_text += " Supporting data: " + "; ".join(snippets) + "."

            cached = get_cached(full_text)
            polished_container = ui.element("div").style("width:100%;")
            with polished_container:
                if cached:
                    _show_polished(cached)

            btn_label = "✨ Re-polish" if cached else "✨ Polish with Claude"
            polish_btn = ui.button(btn_label).classes("brief-polish-btn").style("margin-top:0.6rem;")
            polish_btn.on(
                "click",
                lambda e, ft=full_text, pc=polished_container, pb=polish_btn:
                    asyncio.ensure_future(_trigger_polish(ft, pc, pb)),
            )


def _show_polished(text: str) -> None:
    ui.label("CLAUDE").classes("brief-polish-label")
    ui.element("div").classes("brief-polished-block").text = text


async def _trigger_polish(text: str, container: ui.element, btn) -> None:
    btn.set_text("Polishing…")
    btn.disable()
    result, err = await run.io_bound(llm_polish, text)
    container.clear()
    with container:
        if result:
            _show_polished(result)
        else:
            detail = err or "Unknown error (see server logs)."
            ui.label(f"Polish failed — {detail}").style(
                "color:#f87171; font-size:0.76rem; font-family:'IBM Plex Mono',monospace;"
            )
    btn.set_text("✨ Re-polish")
    btn.enable()


# ── Asset posture section ──────────────────────────────────────────────────────

def _render_asset_posture(state: AppState):
    tenure = _load_tenure_data(state.asset_views)

    by_group = {
        "l1":           [v for v in state.asset_views if v.group == "l1"],
        "equities":     [v for v in state.asset_views if v.group == "equities"],
        "fixed_income": [v for v in state.asset_views if v.group == "fixed_income"],
    }
    group_labels = {
        "l1":           "L1 — CROSS-ASSET",
        "equities":     "EQUITIES",
        "fixed_income": "FIXED INCOME",
    }

    with ui.element("div").style(
        "background:var(--bg-card); border:1px solid var(--border); "
        "border-radius:6px; padding:0.75rem 1rem;"
    ):
        for gk in ("l1", "equities", "fixed_income"):
            views = by_group[gk]
            if not views:
                continue
            ui.label(group_labels[gk]).style(
                "font-size:0.6rem; font-weight:700; color:var(--text-muted); "
                "letter-spacing:0.15em; padding:0.4rem 0 0.25rem; "
                "font-family:'IBM Plex Mono',monospace;"
            )
            for av in views:
                t = tenure.get(av.id)
                entry = asset_verbal(av, t)
                sc = SCORE_COLORS.get(av.direction, SCORE_COLORS["—"])
                with ui.element("div").classes("brief-asset-row"):
                    ui.element("span").style(
                        f"background:{sc['bg']}; color:{sc['text']}; "
                        f"border:1px solid {sc['text']}33; border-radius:4px; "
                        f"padding:1px 7px; font-size:0.72rem; font-weight:700; "
                        f"white-space:nowrap; flex-shrink:0;"
                    ).text = av.direction

                    ui.label(av.name).style(
                        "font-size:0.84rem; min-width:130px; flex-shrink:0; "
                        "font-family:'IBM Plex Mono',monospace;"
                    )

                    verbal_label = entry["verbal"]
                    ui.label(verbal_label).style(
                        f"font-size:0.78rem; color:{sc['text']}; flex-shrink:0; "
                        f"min-width:120px; font-family:'IBM Plex Mono',monospace;"
                    )

                    if entry["note"]:
                        ui.label(entry["note"]).style(
                            "font-size:0.78rem; color:var(--text-muted); flex:1; "
                            "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; "
                            "font-family:'IBM Plex Mono',monospace;"
                        )

                    if entry["held"]:
                        ui.label(entry["held"]).style(
                            "font-size:0.72rem; color:var(--text-faint); "
                            "white-space:nowrap; flex-shrink:0; "
                            "font-family:'IBM Plex Mono',monospace;"
                        )


# ── Public entry point ─────────────────────────────────────────────────────────

def render_briefing(state: AppState, save_indicator, fred_data: list | None = None):
    _inject_css()
    fred_index = {ind.id: ind for ind in (fred_data or [])}
    has_fred = bool(fred_data)
    has_llm = llm_available()

    # ── Section: Opener ───────────────────────────────────────────────────────
    ui.label("OPENER").classes("section-header")
    _render_opener(state)

    # ── Section: Macro narrative ──────────────────────────────────────────────
    with ui.row().style("align-items:center; gap:0.75rem; margin-bottom:0.5rem;"):
        ui.label("MACRO NARRATIVE").classes("section-header").style("margin-bottom:0;")
        if not has_fred:
            ui.label("(FRED data loading…)").style(
                "font-size:0.68rem; color:var(--text-faint); "
                "font-family:'IBM Plex Mono',monospace;"
            )

    for view in state.macro_views:
        _render_macro_card(view, fred_index, has_llm)

    if state.macro_notes and state.macro_notes.strip():
        with ui.element("div").style(
            "background:var(--bg-card); border:1px solid var(--border); "
            "border-radius:6px; padding:0.75rem; margin-bottom:0.75rem;"
        ):
            ui.label("CROSS-CUTTING NOTES").style(
                "font-size:0.6rem; font-weight:700; color:var(--accent); "
                "letter-spacing:0.14em; margin-bottom:0.4rem; "
                "font-family:'IBM Plex Mono',monospace;"
            )
            ui.label(state.macro_notes.strip()).style(
                "font-size:0.84rem; color:var(--text-muted); line-height:1.6; "
                "font-family:'IBM Plex Mono',monospace; white-space:pre-wrap;"
            )

    # ── Section: Asset posture ────────────────────────────────────────────────
    ui.label("ASSET POSTURE").classes("section-header").style("margin-top:1.5rem;")
    _render_asset_posture(state)
