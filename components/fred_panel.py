"""FRED economic data panel — pure inline-style HTML tables with click-to-chart."""

from datetime import datetime
from nicegui import ui
from storage.fred_client import Indicator, GROUPS


def _fmt_as_of(date_str: str) -> str:
    """Format YYYY-MM-DD as 'Mon YYYY' for display (e.g. 'Mar 2025')."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %Y")
    except Exception:
        return date_str

# ── Hardcoded dark-theme palette (no CSS variables — guaranteed to render) ────
_BG      = "#17171e"
_BORDER  = "#2a2a38"
_SEP     = "#1d1d28"      # between rows
_TEXT    = "#dddde8"
_MUTED   = "#9090b0"
_FAINT   = "#505068"
_ACCENT  = "#2dd4bf"
_MONO    = "'IBM Plex Mono','Courier New',monospace"

# Column headers per group (override default "3M / 6M / 12M")
_GROUP_HEADERS: dict[str, tuple] = {
    "Inflation": ("3M Ann", "6M Ann", "12M YoY"),
    "Equities":  ("3M %",   "6M %",   "12M %"),
}
_DEFAULT_HEADERS = ("3M", "6M", "12M")


# ── Chart dialog ──────────────────────────────────────────────────────────────

def _open_chart_dialog(ind: Indicator) -> None:
    if not ind.chart_series:
        return

    dates  = [p["date"] for p in ind.chart_series]
    values = [p["value"] for p in ind.chart_series]

    with ui.dialog() as dialog:
        with ui.card().style(
            f"background:{_BG}; border:1px solid {_BORDER}; border-radius:8px; "
            f"min-width:min(720px,95vw); max-width:95vw; padding:1.25rem 1.5rem 1rem;"
        ):
            with ui.row().style(
                "align-items:center; justify-content:space-between; "
                "width:100%; margin-bottom:0.15rem;"
            ):
                ui.label(ind.name).style(
                    f"font-size:0.88rem; font-weight:700; color:{_ACCENT}; "
                    f"font-family:{_MONO}; letter-spacing:0.05em;"
                )
                ui.button("✕", on_click=dialog.close).style(
                    "background:transparent !important; color:#505068; "
                    "box-shadow:none; font-size:1rem; "
                    "min-width:1.5rem; padding:0 0.4rem;"
                )

            ui.label(
                f"FRED · as of {ind.as_of} · {ind.chart_label} · "
                f"{len(dates)} observations · scroll or drag bottom bar to zoom"
            ).style(
                f"font-size:0.62rem; color:{_FAINT}; font-family:{_MONO}; "
                f"letter-spacing:0.05em; margin-bottom:0.6rem;"
            )

            ui.echart({
                "backgroundColor": _BG,
                "animation": False,
                "grid": {"top": 12, "bottom": 52, "left": 62, "right": 16},
                "xAxis": {
                    "type": "category",
                    "data": dates,
                    "boundaryGap": False,
                    "axisLabel": {
                        "color": _MUTED,
                        "fontSize": 9,
                        "fontFamily": "IBM Plex Mono, monospace",
                        "rotate": 35,
                        "hideOverlap": True,
                    },
                    "axisLine": {"lineStyle": {"color": _BORDER}},
                    "axisTick": {"show": False},
                },
                "yAxis": {
                    "type": "value",
                    "axisLabel": {
                        "color": _MUTED,
                        "fontSize": 9,
                        "fontFamily": "IBM Plex Mono, monospace",
                    },
                    "splitLine": {"lineStyle": {"color": _SEP, "type": "dashed"}},
                    "axisLine": {"show": False},
                },
                "series": [{
                    "type": "line",
                    "data": values,
                    "lineStyle": {"color": _ACCENT, "width": 1.5},
                    "symbol": "none",
                    "areaStyle": {
                        "color": {
                            "type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                            "colorStops": [
                                {"offset": 0, "color": "#2dd4bf28"},
                                {"offset": 1, "color": "#2dd4bf00"},
                            ],
                        }
                    },
                }],
                "tooltip": {
                    "trigger": "axis",
                    "backgroundColor": "#0f0f13",
                    "borderColor": _BORDER,
                    "textStyle": {
                        "color": _TEXT,
                        "fontFamily": "IBM Plex Mono, monospace",
                        "fontSize": 10,
                    },
                },
                "dataZoom": [
                    {"type": "inside", "start": 0, "end": 100},
                    {
                        "type": "slider",
                        "bottom": 4,
                        "height": 18,
                        "fillerColor": "#2dd4bf18",
                        "borderColor": _BORDER,
                        "textStyle": {"color": _MUTED, "fontSize": 8},
                        "handleStyle": {"color": _ACCENT, "borderColor": _ACCENT},
                        "moveHandleStyle": {"color": _ACCENT},
                        "selectedDataBackground": {
                            "lineStyle": {"color": _ACCENT},
                            "areaStyle": {"color": "#2dd4bf18"},
                        },
                    },
                ],
            }).style("height:300px; width:100%;")

    dialog.open()


# ── HTML table helpers (original rendering — preserves exact visual) ───────────

def _th_left(text: str) -> str:
    return (
        f'<td style="text-align:left;padding:0.22rem 1.2rem 0.22rem 0;'
        f'font-size:0.6rem;color:{_FAINT};letter-spacing:0.12em;font-weight:400;'
        f'border-bottom:1px solid {_BORDER};white-space:nowrap;'
        f'font-family:{_MONO};">{text}</td>'
    )


def _th(text: str) -> str:
    return (
        f'<td style="text-align:right;padding:0.22rem 0 0.22rem 1rem;'
        f'font-size:0.6rem;color:{_FAINT};letter-spacing:0.12em;font-weight:400;'
        f'border-bottom:1px solid {_BORDER};white-space:nowrap;'
        f'font-family:{_MONO};">{text}</td>'
    )


def _row(ind: Indicator, last: bool = False) -> str:
    sep = "none" if last else f"1px solid {_SEP}"
    style_override = f"border-bottom:{sep}"
    # Rows with chart data get a pointer cursor and a data attribute the JS bridge uses
    clickable = not ind.error and bool(ind.chart_series)
    tr_open = (
        f'<tr data-fred-id="{ind.id}" style="cursor:pointer">'
        if clickable else '<tr>'
    )
    _td_name_base = (
        f"text-align:left;padding:0.35rem 1.5rem 0.35rem 0;"
        f"{style_override};white-space:nowrap;font-family:{_MONO};"
    )
    if ind.error:
        name_cell = (
            f'<td style="{_td_name_base}">'
            f'<span style="color:{_FAINT};font-size:0.83rem;">{ind.name}</span>'
            f'</td>'
        )
        return (
            f'{tr_open}'
            f'{name_cell}'
            f'<td style="text-align:right;padding:0.38rem 0 0.38rem 1rem;color:{_FAINT};'
            f'{style_override};font-family:{_MONO};font-size:0.83rem;font-style:italic;">N/A</td>'
            f'<td style="text-align:right;padding:0.38rem 0 0.38rem 1rem;color:{_FAINT};'
            f'{style_override};font-family:{_MONO};font-size:0.83rem;">—</td>'
            f'<td style="text-align:right;padding:0.38rem 0 0.38rem 1rem;color:{_FAINT};'
            f'{style_override};font-family:{_MONO};font-size:0.83rem;">—</td>'
            f'<td style="text-align:right;padding:0.38rem 0 0.38rem 1rem;color:{_FAINT};'
            f'{style_override};font-family:{_MONO};font-size:0.83rem;">—</td>'
            f'</tr>'
        )
    name_cell = (
        f'<td style="{_td_name_base}">'
        f'<span style="color:{_TEXT};font-size:0.83rem;">{ind.name}</span>'
        f'<span style="display:block;color:{_FAINT};font-size:0.62rem;'
        f'margin-top:0.06rem;letter-spacing:0.04em;">{_fmt_as_of(ind.as_of)}</span>'
        f'</td>'
    )
    return (
        f'{tr_open}'
        f'{name_cell}'
        f'<td style="text-align:right;padding:0.38rem 0 0.38rem 1rem;color:{_TEXT};font-weight:600;'
        f'{style_override};white-space:nowrap;font-family:{_MONO};font-size:0.83rem;">{ind.value_label}</td>'
        f'<td style="text-align:right;padding:0.38rem 0 0.38rem 1rem;color:{ind.d3m_color};'
        f'{style_override};white-space:nowrap;font-family:{_MONO};font-size:0.83rem;">{ind.d3m_label}</td>'
        f'<td style="text-align:right;padding:0.38rem 0 0.38rem 1rem;color:{ind.d6m_color};'
        f'{style_override};white-space:nowrap;font-family:{_MONO};font-size:0.83rem;">{ind.d6m_label}</td>'
        f'<td style="text-align:right;padding:0.38rem 0 0.38rem 1rem;color:{ind.d12m_color};'
        f'{style_override};white-space:nowrap;font-family:{_MONO};font-size:0.83rem;">{ind.d12m_label}</td>'
        f'</tr>'
    )


def _group_table(group_name: str, inds: list[Indicator]) -> str:
    h = _GROUP_HEADERS.get(group_name, _DEFAULT_HEADERS)
    rows = "".join(_row(ind, last=(i == len(inds) - 1)) for i, ind in enumerate(inds))
    return (
        f'<div style="overflow-x:auto;background:{_BG};border:1px solid {_BORDER};'
        f'border-radius:6px;padding:0.5rem 0.85rem 0.6rem;margin-bottom:1.25rem;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<tbody>'
        f'<tr>'
        f'{_th_left("INDICATOR")}'
        f'{_th("CURRENT")}'
        f'{_th(h[0])}'
        f'{_th(h[1])}'
        f'{_th(h[2])}'
        f'</tr>'
        f'{rows}'
        f'</tbody>'
        f'</table>'
        f'</div>'
    )


# ── Main render ───────────────────────────────────────────────────────────────

def render_fred_panel(indicators: list[Indicator], timestamp: str) -> None:

    # Header
    with ui.row().style("align-items:baseline; gap:0.75rem; margin-bottom:1.5rem;"):
        ui.label("ECONOMIC DATA").style(
            f"font-size:0.72rem; font-weight:700; color:{_ACCENT}; "
            f"letter-spacing:0.18em; font-family:{_MONO};"
        )
        ui.label(f"via FRED · {timestamp}").style(
            f"font-size:0.68rem; color:{_FAINT}; font-family:{_MONO};"
        )

    if not indicators:
        ui.html(
            f'<p style="color:{_MUTED};font-size:0.82rem;font-family:{_MONO};margin-top:2rem;">'
            f'No data. Check that FRED_API_KEY is set and the app can reach '
            f'api.stlouisfed.org.</p>'
        )
        return

    # ── Hidden click-trigger buttons (one per chartable indicator) ────────────
    # Each button is invisible and off-screen. The JS bridge below routes
    # <tr data-fred-id="..."> clicks to the matching button, firing the
    # Python on_click handler which opens the chart dialog.
    with ui.element("div").style(
        "position:absolute;left:-9999px;top:-9999px;width:0;height:0;overflow:hidden;"
    ):
        for ind in indicators:
            if ind.chart_series and not ind.error:
                def _make_handler(i: Indicator):
                    def _h(_e): _open_chart_dialog(i)
                    return _h
                (ui.button()
                    .props(f'data-fred-id="{ind.id}"')
                    .classes("fred-chart-trigger")
                    .on("click", _make_handler(ind)))

    # ── Group tables (original HTML rendering) ────────────────────────────────
    grouped: dict[str, list[Indicator]] = {g: [] for g in GROUPS}
    for ind in indicators:
        grouped.setdefault(ind.group, []).append(ind)

    for idx, group_name in enumerate(GROUPS):
        inds = grouped.get(group_name, [])
        if not inds:
            continue
        if idx > 0:
            ui.element("div").style("height:1.75rem;")
        ui.label(group_name.upper()).classes("section-header")
        ui.html(_group_table(group_name, inds))

    # ── Legend ────────────────────────────────────────────────────────────────
    ui.html(
        f'<div style="display:flex;flex-wrap:wrap;gap:0.5rem 1.5rem;'
        f'margin-top:0.25rem;font-family:{_MONO};">'
        + "".join(
            f'<span style="display:inline-flex;align-items:center;gap:0.4rem;">'
            f'<span style="width:7px;height:7px;border-radius:50%;'
            f'background:{c};display:inline-block;flex-shrink:0;"></span>'
            f'<span style="font-size:0.64rem;color:{_FAINT};">{lbl}</span>'
            f'</span>'
            for c, lbl in [
                ("#4ade80", "improving / favorable"),
                ("#f87171", "deteriorating / adverse"),
                ("#9090b0", "neutral"),
            ]
        )
        + f'<span style="font-size:0.64rem;color:{_FAINT};margin-left:0.5rem;">'
          f'· click any row to view time series</span>'
        + "</div>"
    )

    # ── JS bridge: wire table-row clicks → hidden trigger buttons ─────────────
    # Runs after NiceGUI pushes the DOM update so elements are present.
    ui.run_javascript("""
        setTimeout(function () {
            document.querySelectorAll('tr[data-fred-id]').forEach(function (tr) {
                tr.addEventListener('click', function () {
                    var btn = document.querySelector(
                        'button.fred-chart-trigger[data-fred-id="' +
                        tr.getAttribute('data-fred-id') + '"]'
                    );
                    if (btn) btn.click();
                });
            });
        }, 300);
    """)
