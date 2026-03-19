from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from itertools import groupby
from nicegui import ui
from models.schema import AppState, ViewChangeEntry
from storage.persistence import save_state


# ── Color maps (mirrors macro_views.py) ───────────────────────────────────────

_DIR_BG = {
    "Bullish": "1a6b3a", "Neutral": "2a2a38",
    "Bearish": "6b1a1a", "No View": "1e1e24",
}
_DIR_FG = {
    "Bullish": "4ade80", "Neutral": "a0a0b8",
    "Bearish": "f87171", "No View": "555566",
}
_CONV_FILL = {"High": 3, "Medium": 2, "Low": 1, "—": 0}
_CONV_COLOR = {
    "High": "#2dd4bf", "Medium": "#a0a0b8", "Low": "#9ca3af", "—": "#44445a",
}

# Left-border accent on each card — keyed to the *new* value
_BORDER_COLOR = {
    # direction
    "Bullish": "#4ade80", "Neutral": "#6b7280", "Bearish": "#f87171",
    "No View": "#374151",
    # conviction
    "High": "#2dd4bf", "Medium": "#a0a0b8", "Low": "#9ca3af", "—": "#374151",
}


def _dir_badge(value: str) -> str:
    bg = _DIR_BG.get(value, _DIR_BG["No View"])
    fg = _DIR_FG.get(value, _DIR_FG["No View"])
    return (
        f'<span style="background:#{bg}; color:#{fg}; padding:2px 10px; border-radius:4px; '
        f'font-size:0.75rem; font-weight:700; letter-spacing:0.05em; '
        f'border:1px solid #{fg}33; white-space:nowrap;">{value}</span>'
    )


def _conv_html(value: str) -> str:
    filled = _CONV_FILL.get(value, 0)
    on, off = "#2dd4bf", "#2a2a3e"
    heights = ["7px", "11px", "15px"]
    bars = "".join(
        f'<span style="display:inline-block; width:4px; height:{h}; '
        f'background:{on if i < filled else off}; border-radius:1px; '
        f'margin-right:2px; vertical-align:bottom;"></span>'
        for i, h in enumerate(heights)
    )
    color = _CONV_COLOR.get(value, _CONV_COLOR["—"])
    return (
        f'<span style="display:inline-flex; align-items:flex-end;">{bars}</span>'
        f'<span style="color:{color}; font-size:0.75rem; font-weight:700; margin-left:6px;">{value}</span>'
    )


def _fmt_time(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    h = dt.strftime("%I").lstrip("0") or "12"
    return f"{h}{dt.strftime(':%M %p')}"


def _entry_date_key(entry: ViewChangeEntry) -> str:
    dt = entry.timestamp
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d")  # sortable key


def _entry_date_label(key: str) -> str:
    dt = datetime.strptime(key, "%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = datetime.now().replace(day=datetime.now().day - 1).strftime("%Y-%m-%d") if datetime.now().day > 1 else ""
    if key == today:
        return "Today"
    if key == yesterday:
        return "Yesterday"
    return dt.strftime("%B %d, %Y")


# ── Public renderer ────────────────────────────────────────────────────────────

def render_view_change_log(state: AppState, save_indicator):
    def save():
        save_state(state)
        save_indicator()

    # ── Stats bar ──────────────────────────────────────────────────────────────
    _render_stats(state)

    ui.element("div").style("height:1px; background:var(--border); width:100%; margin-bottom:1.25rem;")

    # ── Filter bar ─────────────────────────────────────────────────────────────
    var_names = ["All"] + [v.name for v in state.macro_views]
    filters = {"variable": "All", "field": "All"}
    entries_container = ui.element("div").style("width:100%;")

    def refresh():
        entries_container.clear()
        with entries_container:
            _render_entries(state, filters, save)

    with ui.row().style("gap:0.75rem; align-items:center; margin-bottom:1.25rem; flex-wrap:wrap;"):
        ui.label("FILTER").style(
            "font-size:0.62rem; font-weight:700; color:var(--text-muted); letter-spacing:0.15em;"
        )
        ui.select(
            var_names, value="All",
            on_change=lambda e: (filters.update({"variable": e.value}), refresh())
        ).classes("dark-input").style("width:190px;")

        ui.select(
            ["All", "Direction", "Conviction"], value="All",
            on_change=lambda e: (filters.update({"field": e.value}), refresh())
        ).classes("dark-input").style("width:145px;")

    refresh()


def _render_stats(state: AppState):
    log = state.view_change_log

    with ui.row().style(
        "gap:0; margin-bottom:1.25rem; flex-wrap:wrap; align-items:stretch; "
        "background:var(--bg-card); border:1px solid var(--border); border-radius:6px; overflow:hidden;"
    ):
        # Stat 1: total changes
        _stat_cell(str(len(log)), "total changes logged")

        if log:
            _stat_divider()

            # Stat 2: most changed variable
            counts = Counter(e.view_name for e in log)
            top_name, top_count = counts.most_common(1)[0]
            _stat_cell(top_name, f"most active · {top_count} {'change' if top_count == 1 else 'changes'}")

            _stat_divider()

            # Stat 3: last change
            last_dt = log[0].timestamp
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            days_ago = (datetime.now(tz=timezone.utc) - last_dt).days
            age_label = "today" if days_ago == 0 else ("yesterday" if days_ago == 1 else f"{days_ago}d ago")
            _stat_cell(age_label, f"last change · {log[0].view_name}")

            _stat_divider()

            # Stat 4: direction vs conviction split
            dir_count = sum(1 for e in log if e.field == "direction")
            conv_count = len(log) - dir_count
            _stat_cell(f"{dir_count} / {conv_count}", "direction / conviction")


def _stat_cell(value: str, label: str):
    with ui.column().style("gap:2px; padding:0.9rem 1.5rem; align-items:flex-start; flex:1; min-width:140px;"):
        ui.label(value).style(
            "font-size:1.1rem; font-weight:700; color:var(--accent); line-height:1; white-space:nowrap;"
        )
        ui.label(label).style(
            "font-size:0.65rem; color:var(--text-muted); letter-spacing:0.06em; white-space:nowrap;"
        )


def _stat_divider():
    ui.element("div").style("width:1px; background:var(--border); flex-shrink:0;")


# ── Entry list ─────────────────────────────────────────────────────────────────

def _render_entries(state: AppState, filters: dict, save):
    log = state.view_change_log

    # Apply filters
    visible = [
        e for e in log
        if (filters["variable"] == "All" or e.view_name == filters["variable"])
        and (filters["field"] == "All" or e.field == filters["field"].lower())
    ]

    if not visible:
        with ui.column().style(
            "width:100%; align-items:center; padding:5rem 0; gap:0.5rem;"
        ):
            ui.label("NO ENTRIES").style(
                "font-size:0.72rem; letter-spacing:0.2em; font-weight:700; color:var(--text-faint);"
            )
            if state.view_change_log:
                ui.label("No entries match the current filters.").style(
                    "font-size:0.82rem; color:var(--text-faint);"
                )
            else:
                ui.label(
                    "Direction and conviction changes on the Macro Views tab will appear here automatically."
                ).style(
                    "font-size:0.82rem; color:var(--text-faint); text-align:center; "
                    "max-width:420px; line-height:1.7;"
                )
        return

    # Group by calendar date (entries already newest-first in state)
    for date_key, group_iter in groupby(visible, key=_entry_date_key):
        group = list(group_iter)

        # Date separator
        with ui.row().style(
            "align-items:center; gap:1rem; margin:1.1rem 0 0.6rem; width:100%;"
        ):
            ui.element("div").style("flex:1; height:1px; background:var(--border);")
            ui.label(_entry_date_label(date_key)).style(
                "font-size:0.65rem; font-weight:700; color:var(--text-muted); "
                "letter-spacing:0.12em; white-space:nowrap;"
            )
            ui.element("div").style("flex:1; height:1px; background:var(--border);")

        for entry in group:
            _entry_card(entry, save)


# ── Single entry card ──────────────────────────────────────────────────────────

def _entry_card(entry: ViewChangeEntry, save):
    accent = _BORDER_COLOR.get(entry.new_value, "#374151")

    with ui.element("div").style(
        f"background:var(--bg-card); border:1px solid var(--border); border-radius:6px; "
        f"border-left:3px solid {accent}; padding:0.75rem 1rem 0.6rem; "
        f"margin-bottom:0.4rem; width:100%;"
    ):
        # ── Header row: variable name + field tag + timestamp ──────────────────
        with ui.row().style(
            "align-items:center; justify-content:space-between; margin-bottom:0.55rem; gap:0.5rem; flex-wrap:wrap;"
        ):
            with ui.row().style("align-items:center; gap:0.6rem;"):
                ui.label(entry.view_name).style(
                    "font-weight:700; font-size:0.9rem; color:var(--text-primary);"
                )
                field_label = "DIRECTION" if entry.field == "direction" else "CONVICTION"
                field_color = "var(--accent)" if entry.field == "conviction" else "var(--text-muted)"
                ui.label(field_label).style(
                    f"font-size:0.6rem; font-weight:700; color:{field_color}; "
                    f"letter-spacing:0.15em; padding:1px 6px; border-radius:3px; "
                    f"border:1px solid {field_color}44;"
                )
            ui.label(_fmt_time(entry.timestamp)).style(
                "font-size:0.72rem; color:var(--text-faint); white-space:nowrap; flex-shrink:0;"
            )

        # ── Change row: old → new ──────────────────────────────────────────────
        with ui.row().style("align-items:center; gap:0.6rem; flex-wrap:wrap; margin-bottom:0.6rem;"):
            if entry.field == "direction":
                ui.html(_dir_badge(entry.old_value))
                ui.label("→").style("color:var(--text-faint); font-size:0.85rem;")
                ui.html(_dir_badge(entry.new_value))
            else:
                ui.html(_conv_html(entry.old_value))
                ui.label("→").style("color:var(--text-faint); font-size:0.85rem; flex-shrink:0;")
                ui.html(_conv_html(entry.new_value))

        # ── Reason: inline editable ────────────────────────────────────────────
        _reason_row(entry, save)


def _reason_row(entry: ViewChangeEntry, save):
    state_ref = {"editing": False}

    if entry.reason:
        display_text = f'"{entry.reason}"'
        display_style = (
            "font-style:italic; color:var(--text-muted); font-size:0.8rem; "
            "cursor:pointer; line-height:1.5; border-bottom:1px dashed var(--border);"
        )
    else:
        display_text = "+ add reason…"
        display_style = (
            "color:var(--text-faint); font-size:0.75rem; cursor:pointer; "
            "letter-spacing:0.04em; border-bottom:1px dashed transparent;"
        )

    label_el = ui.label(display_text).style(display_style)
    input_el = ui.input(
        value=entry.reason,
        placeholder="Why did this change? (e.g. 'hot CPI print shifted the growth-inflation mix')"
    ).classes("dark-input w-full").style("display:none; font-size:0.82rem;")

    def on_label_click(e):
        if state_ref["editing"]:
            return
        state_ref["editing"] = True
        label_el.style("display:none;")
        input_el.style("display:inline-flex; width:100%;")
        input_el.run_method("focus")

    def on_input_blur(e):
        new_reason = input_el.value.strip()
        entry.reason = new_reason
        save()
        if new_reason:
            label_el.text = f'"{new_reason}"'
            label_el.style(
                "font-style:italic; color:var(--text-muted); font-size:0.8rem; "
                "cursor:pointer; line-height:1.5; border-bottom:1px dashed var(--border);"
            )
        else:
            label_el.text = "+ add reason…"
            label_el.style(
                "color:var(--text-faint); font-size:0.75rem; cursor:pointer; "
                "letter-spacing:0.04em; border-bottom:1px dashed transparent;"
            )
        input_el.style("display:none;")
        label_el.style(label_el.style + " display:inline;")
        state_ref["editing"] = False

    label_el.on("click", on_label_click)
    input_el.on("blur", on_input_blur)
