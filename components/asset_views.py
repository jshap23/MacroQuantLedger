from __future__ import annotations
import json
from datetime import datetime, timezone, date
from pathlib import Path
from nicegui import ui
from models.schema import AppState, AssetView
from storage.persistence import save_state
from components.status_bar import days_since, staleness_color

_SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"

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
            with ui.column().style("flex:1; min-width:280px; gap:0;"):
                _group_header("EQUITIES")
                for av in by_group["equities"]:
                    _l2_row(av, save)

            with ui.column().style("flex:1; min-width:280px; gap:0;"):
                _group_header("FIXED INCOME")
                for av in by_group["fixed_income"]:
                    _l2_row(av, save)

        # ── Conviction Tenure ─────────────────────────────────────────────────
        _render_tenure_table(state, save)


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


def _note_preview_input(av: AssetView, save, *, placeholder: str, font_size: str | None, stale_lbl: list | None = None):
    """Read-only note strip; click opens the full editor (no separate expand button)."""
    style = "flex:1; min-width:0; cursor:pointer;"
    if font_size:
        style += f" font-size:{font_size};"
    note_in = ui.input(value=av.note, placeholder=placeholder).classes("dark-input").style(style)
    note_in.props("readonly")
    note_in.tooltip("Click to edit note")
    note_in.on("click", lambda _: _open_note_dialog(av, note_in, save, stale_lbl=stale_lbl))
    return note_in


def _l1_row(av: AssetView, save):
    with ui.row().classes("w-full asset-row-l1").style("align-items:center; gap:0.75rem;"):
        # Score badge (dynamic)
        badge = ui.html(_score_badge_html(av.direction)).style("flex-shrink:0;")

        ui.label(av.name).style(
            "font-weight:700; font-size:0.95rem; min-width:140px; flex-shrink:0;"
        )

        stale_lbl = [None]

        ui.select(
            SCORE_OPTIONS,
            value=av.direction,
            on_change=lambda e, a=av, b=badge: (
                setattr(a, "direction", e.value),
                b.set_content(_score_badge_html(e.value)),
                _touch_save(a, None, None, save),
                _refresh_staleness(stale_lbl[0], a),
            )
        ).classes("dark-input").style("width:90px; flex-shrink:0;")

        _note_preview_input(
            av,
            save,
            placeholder="Click to edit cross-asset thesis…",
            font_size=None,
            stale_lbl=stale_lbl,
        )

        stale_lbl[0] = _staleness_label(av)


def _l2_row(av: AssetView, save):
    with ui.row().classes("w-full asset-row-l2").style("align-items:center; gap:0.5rem;"):
        # Score dot (dynamic)
        dot = ui.element("span").style(_score_dot_style(av.direction))

        ui.label(av.name).style(
            "font-size:0.85rem; min-width:130px; flex-shrink:0; color:var(--text-primary);"
        )

        stale_lbl = [None]

        ui.select(
            SCORE_OPTIONS,
            value=av.direction,
            on_change=lambda e, a=av, d=dot: (
                setattr(a, "direction", e.value),
                d.style(_score_dot_style(e.value)),
                _touch_save(a, None, None, save),
                _refresh_staleness(stale_lbl[0], a, compact=True),
            )
        ).classes("dark-input").style("width:80px; flex-shrink:0;")

        _note_preview_input(
            av,
            save,
            placeholder="Click to edit thesis…",
            font_size="0.82rem",
            stale_lbl=stale_lbl,
        )

        stale_lbl[0] = _staleness_label(av, compact=True)



def _staleness_label(av: AssetView, compact: bool = False):
    d = days_since(av.last_touched)
    text = "—" if d is None else ("today" if d == 0 else f"{d}d")
    color = staleness_color(d)
    size = "0.7rem" if compact else "0.75rem"
    width = "38px" if compact else "52px"
    lbl = ui.label(text).style(
        f"color:{color}; font-size:{size}; white-space:nowrap; "
        f"flex-shrink:0; min-width:{width}; text-align:right;"
    )
    return lbl


def _refresh_staleness(lbl, av: AssetView, compact: bool = False):
    d = days_since(av.last_touched)
    text = "—" if d is None else ("today" if d == 0 else f"{d}d")
    color = staleness_color(d)
    size = "0.7rem" if compact else "0.75rem"
    lbl.text = text
    lbl.style(f"color:{color}; font-size:{size};")


def _load_tenure_data(asset_views: list) -> dict:
    """Read daily snapshots and return tenure info per asset view id."""
    snap_files = sorted(_SNAPSHOTS_DIR.glob("state_*.json"))
    timeline: list[tuple[date, dict]] = []
    for f in snap_files:
        try:
            snap_date = date.fromisoformat(f.stem.replace("state_", ""))
            data = json.loads(f.read_text(encoding="utf-8"))
            scores = {av["id"]: av["direction"] for av in data.get("asset_views", [])}
            timeline.append((snap_date, scores))
        except Exception:
            continue

    today = date.today()
    current_scores = {av.id: av.direction for av in asset_views}
    timeline.append((today, current_scores))

    result = {}
    for av in asset_views:
        av_id = av.id
        changed_date = None
        prev_score = None

        for i in range(len(timeline) - 1, 0, -1):
            snap_date, scores = timeline[i]
            _, prev_scores = timeline[i - 1]
            cur = scores.get(av_id)
            prv = prev_scores.get(av_id)
            if cur != prv:
                changed_date = snap_date
                prev_score = prv
                break

        if changed_date is not None:
            days_held = (today - changed_date).days
            unknown_start = False
        elif timeline:
            days_held = (today - timeline[0][0]).days
            unknown_start = True
        else:
            days_held = None
            unknown_start = True

        result[av_id] = {
            "prev_score": prev_score or "—",
            "changed_date": changed_date,
            "days_held": days_held,
            "unknown_start": unknown_start,
        }
    return result


def _held_style(days: int | None, unknown: bool) -> tuple[str, str]:
    """Return (text, color) for the held-duration cell."""
    if days is None:
        return "—", "var(--text-muted)"
    if days == 0:
        text = "today"
    elif unknown:
        text = f">{days}d"
    else:
        text = f"{days}d"
    if days <= 14:
        color = "#4ade80"
    elif days <= 60:
        color = "var(--text-primary)"
    elif days <= 120:
        color = "#fb923c"
    else:
        color = "#f87171"
    return text, color


def _render_tenure_table(state: AppState, save):
    ui.label("CONVICTION TENURE").classes("section-header").style("margin-top:2rem;")
    tenure = _load_tenure_data(state.asset_views)

    with ui.column().classes("w-full").style(
        "background:var(--bg-card); border:1px solid var(--border); "
        "border-radius:6px; padding:0.75rem 1rem; gap:0;"
    ):
        # Column headers
        with ui.row().classes("w-full").style(
            "align-items:center; gap:0.5rem; padding:0 0 0.4rem; "
            "border-bottom:1px solid var(--border); margin-bottom:0.25rem;"
        ):
            for text, width in [
                ("ASSET", "160px"), ("SCORE", "60px"),
                ("HELD", "64px"), ("SINCE", "60px"), ("PREV", "52px"),
            ]:
                ui.label(text).style(
                    f"font-size:0.6rem; font-weight:700; color:var(--text-muted); "
                    f"letter-spacing:0.12em; min-width:{width}; flex-shrink:0;"
                )

        by_group = {
            "l1":           [v for v in state.asset_views if v.group == "l1"],
            "equities":     [v for v in state.asset_views if v.group == "equities"],
            "fixed_income": [v for v in state.asset_views if v.group == "fixed_income"],
        }
        for group_key, group_label in [
            ("l1", "L1 CROSS-ASSET"),
            ("equities", "EQUITIES"),
            ("fixed_income", "FIXED INCOME"),
        ]:
            ui.label(group_label).style(
                "font-size:0.58rem; font-weight:700; color:var(--text-muted); "
                "letter-spacing:0.15em; padding:0.55rem 0 0.2rem;"
            )
            for av in by_group[group_key]:
                t = tenure.get(av.id, {})
                days = t.get("days_held")
                held_text, held_color = _held_style(days, t.get("unknown_start", True))
                changed = t.get("changed_date")
                since_text = changed.strftime("%b %#d") if changed else "—"
                prev = t.get("prev_score", "—")
                if prev not in SCORE_OPTIONS:
                    prev = "—"

                with ui.row().classes("w-full").style(
                    "align-items:center; gap:0.5rem; padding:0.2rem 0; "
                    "border-bottom:1px solid #ffffff08;"
                ):
                    ui.label(av.name).style(
                        "font-size:0.82rem; min-width:160px; flex-shrink:0; "
                        "color:var(--text-primary); white-space:nowrap; overflow:hidden; "
                        "text-overflow:ellipsis;"
                    )
                    ui.html(_score_badge_html(av.direction)).style(
                        "flex-shrink:0; min-width:60px;"
                    )
                    ui.label(held_text).style(
                        f"color:{held_color}; font-size:0.82rem; font-weight:600; "
                        f"min-width:64px; flex-shrink:0;"
                    )
                    ui.label(since_text).style(
                        "font-size:0.78rem; color:var(--text-muted); "
                        "min-width:60px; flex-shrink:0;"
                    )
                    ui.html(_score_badge_html(prev)).style(
                        "flex-shrink:0; min-width:52px; opacity:0.55;"
                    )


def _touch_save(av: AssetView, field: str | None, value, save):
    if field is not None:
        setattr(av, field, value)
    av.last_touched = datetime.now(tz=timezone.utc)
    save()


def _open_note_dialog(av: AssetView, note_in, save, *, stale_lbl: list | None = None):
    """Modal editor for the row note (av.note); syncs inline input on Done."""
    with ui.dialog() as dialog, ui.card().style(
        "background:var(--bg-card); color:var(--text-primary); "
        "font-family:'IBM Plex Mono',monospace; min-width:min(560px,92vw); padding:1.5rem;"
    ):
        ui.label(av.name).style(
            "font-size:1rem; font-weight:700; color:var(--accent); margin-bottom:0.75rem;"
        )
        ta = ui.textarea(
            placeholder="Thesis, risks, catalysts — as much detail as you need…",
        ).classes("w-full dark-input").style("min-height:min(280px,40vh); font-size:0.88rem;")
        ta.value = note_in.value

        def on_done():
            _touch_save(av, "note", ta.value, save)
            note_in.set_value(av.note)
            if stale_lbl and stale_lbl[0] is not None:
                _refresh_staleness(stale_lbl[0], av)
            dialog.close()

        with ui.row().style("gap:0.5rem; justify-content:flex-end; margin-top:1rem;"):
            ui.button("Cancel", on_click=dialog.close).style(
                "background:transparent; color:var(--text-muted); "
                "border:1px solid var(--border); box-shadow:none; "
                "font-family:'IBM Plex Mono',monospace;"
            )
            ui.button("Done", on_click=on_done).style(
                "background:var(--accent); color:var(--bg-primary); "
                "border:1px solid var(--accent); box-shadow:none; "
                "font-family:'IBM Plex Mono',monospace; font-weight:700;"
            )

    dialog.open()
