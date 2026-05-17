"""Attribution tab — were your macro and asset views right?"""
from __future__ import annotations

from datetime import date
from nicegui import ui
from models.schema import AppState
from services.attribution import (
    ASSET_BENCH,
    MACRO_BENCH,
    compute_asset_attribution,
    compute_macro_attribution,
    ScorePeriod,
    ScoreAnalysis,
    AttributionSummary,
)

_CSS_INJECTED = False

# ── Hardcoded dark-theme palette (matches fred_panel.py) ──────────────────────
_BG      = "#17171e"
_BORDER  = "#2a2a38"
_SEP     = "#1d1d28"
_TEXT    = "#dddde8"
_MUTED   = "#9090b0"
_FAINT   = "#505068"
_ACCENT  = "#2dd4bf"
_GREEN   = "#4ade80"
_RED     = "#f87171"
_MONO    = "'IBM Plex Mono','Courier New',monospace"


def _inject_css():
    global _CSS_INJECTED
    if _CSS_INJECTED:
        return
    _CSS_INJECTED = True
    ui.add_head_html('''<style id="mq-attribution-css">
        .attr-summary-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 1rem 1.2rem;
            min-width: 140px;
            flex: 1;
            text-align: center;
            transition: border-color 0.15s;
        }
        .attr-summary-card:hover {
            border-color: var(--border-strong);
        }
        .attr-summary-card .attr-value {
            font-size: 1.6rem;
            font-weight: 700;
            font-family: 'IBM Plex Mono', monospace;
        }
        .attr-summary-card .attr-label {
            font-size: 0.65rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            color: var(--text-muted);
            margin-top: 0.25rem;
        }
        .attr-section {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.75rem 1rem;
            margin-bottom: 1rem;
        }
        .attr-row {
            display: grid;
            align-items: center;
            gap: 0.5rem;
            padding: 0.35rem 0.75rem;
            border-bottom: 1px solid var(--border);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.78rem;
            transition: background 0.12s;
        }
        .attr-row:last-child { border-bottom: none; }
        .attr-row:hover { background: var(--bg-hover); }
        .attr-hdr {
            display: grid;
            align-items: center;
            gap: 0.5rem;
            padding: 0.3rem 0;
            border-bottom: 1px solid var(--border-strong);
            background: var(--bg-status);
            border-radius: 6px 6px 0 0;
            font-family: 'IBM Plex Mono', monospace;
        }
        .attr-chart-wrap {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 1rem;
            margin-bottom: 1.5rem;
        }
        .attr-streak-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            padding: 3px 10px;
            border-radius: 4px;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            white-space: nowrap;
            font-family: 'IBM Plex Mono', monospace;
            align-self: center;
        }
    </style>''')


def _stat_card(value: str, label: str, color: str = "var(--accent)"):
    with ui.element("div").classes("attr-summary-card"):
        ui.label(value).classes("attr-value").style(f"color:{color};")
        ui.label(label).classes("attr-label")


def _verdict_html(verdict: str) -> tuple[str, str]:
    """Return (icon, color) for a verdict."""
    if verdict == "good":
        return "✓", _GREEN
    if verdict == "bad":
        return "✗", _RED
    if verdict == "neutral":
        return "—", _MUTED
    return "—", _FAINT


def _ret_str(ret: float | None) -> str:
    if ret is None:
        return "—"
    return f"{ret:+.1f}%"


def _period_str(start: date, end: date | None) -> str:
    if end is None:
        return f"{start.isoformat()} → today"
    return f"{start.isoformat()} → {end.isoformat()}"


# ── ECharts timeline chart ────────────────────────────────────────────────────

def _build_chart_option(periods_for_view: list[ScorePeriod]) -> dict:
    """Build an echarts option dict for one asset view's price + score-change overlay."""
    if not periods_for_view:
        return {}

    chart_data = periods_for_view[0].chart_series
    if not chart_data:
        return {}

    dates = [p["date"] for p in chart_data]
    values = [p["value"] for p in chart_data]
    date_index = {d: i for i, d in enumerate(dates)}

    # Build markLine data from score change dates (skip the first period start — that's the initial state)
    mark_lines = []
    for i, p in enumerate(periods_for_view):
        start_str = p.start_date.isoformat()
        idx = date_index.get(start_str)
        if idx is None:
            # Find nearest date on or after
            for j, d in enumerate(dates):
                if d >= start_str:
                    idx = j
                    break
        if idx is None:
            continue

        icon, color = _verdict_html(p.verdict)
        label_text = f"{p.score}"

        mark_lines.append({
            "xAxis": idx,
            "lineStyle": {
                "color": color,
                "width": 1.5,
                "type": "dashed",
                "opacity": 0.7,
            },
            "label": {
                "formatter": label_text,
                "color": color,
                "fontSize": 10,
                "fontWeight": "bold",
                "fontFamily": "IBM Plex Mono, monospace",
                "position": "insideStartTop",
            },
        })

    # Mark areas: shade periods with subtle green/red wash
    mark_areas = []
    for p in periods_for_view:
        start_str = p.start_date.isoformat()
        end_str = (p.end_date or date.today()).isoformat()
        start_idx = date_index.get(start_str)
        end_idx = date_index.get(end_str)

        if start_idx is None or end_idx is None:
            continue
        if p.verdict not in ("good", "bad"):
            continue

        area_color = "#4ade8008" if p.verdict == "good" else "#f8717108"
        mark_areas.append([
            {"xAxis": start_idx, "itemStyle": {"color": area_color}},
            {"xAxis": end_idx},
        ])

    series_config = {
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
    }
    if mark_lines:
        series_config["markLine"] = {
            "symbol": "none",
            "data": mark_lines,
            "animation": False,
        }
    if mark_areas:
        series_config["markArea"] = {
            "data": mark_areas,
            "silent": True,
        }

    return {
        "backgroundColor": _BG,
        "animation": False,
        "grid": {"top": 20, "bottom": 52, "left": 62, "right": 16},
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
        "series": [series_config],
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
    }


def _render_attribution_chart(periods: list[ScorePeriod]):
    """Render an interactive echarts chart with a dropdown to select asset view."""
    # Group periods by view_id, skip views with no chart data
    by_view: dict[str, list[ScorePeriod]] = {}
    for p in periods:
        if p.chart_series:
            by_view.setdefault(p.view_id, []).append(p)

    if not by_view:
        return

    # Build options list for dropdown
    view_options = []
    for vid, vperiods in by_view.items():
        name = vperiods[0].view_name
        ticker = vperiods[0].benchmark_label
        view_options.append({"value": vid, "label": f"{name}  ({ticker})"})

    # Sort by name
    view_options.sort(key=lambda o: o["label"])

    current_view = {"id": view_options[0]["value"]}

    with ui.element("div").classes("attr-chart-wrap"):
        ui.label("BENCHMARK CHART").classes("section-header").style("margin-bottom:0.75rem;")

        # Dropdown row
        chart_ref = {"el": None}
        with ui.row().style("gap:0.75rem; align-items:center; margin-bottom:0.75rem;"):
            ui.label("View:").style(
                f"font-size:0.7rem; color:{_MUTED}; font-family:{_MONO}; letter-spacing:0.08em;"
            )
            select = ui.select(
                options=view_options,
                on_change=lambda e: _update_chart(e.value, chart_ref["el"], by_view),
            ).style("min-width:220px;").classes("dark-input")
            select.value = view_options[0]["value"]

            # Legend
            with ui.row().style("gap:1rem; align-items:center; margin-left:auto;"):
                for icon, color, label in [("✓", _GREEN, "Good"), ("✗", _RED, "Bad"), ("—", _MUTED, "Neutral")]:
                    with ui.row().style("gap:0.25rem; align-items:center;"):
                        ui.element("span").style(
                            f"width:10px; height:2px; background:{color}; display:inline-block;"
                        )
                        ui.label(label).style(
                            f"font-size:0.62rem; color:{_FAINT}; font-family:{_MONO};"
                        )

        # Chart
        initial_periods = by_view.get(current_view["id"], [])
        option = _build_chart_option(initial_periods)
        chart_ref["el"] = ui.echart(option).style("height:280px; width:100%;")

        ui.label(
            "Dashed vertical lines mark score changes. "
            "Shaded areas show period duration (green = good call, red = bad call)."
        ).style(f"font-size:0.62rem; color:{_FAINT}; margin-top:0.5rem; font-family:{_MONO};")


def _update_chart(view_id, chart_el, by_view: dict):
    """Update the echarts chart when the dropdown changes."""
    if chart_el is None:
        return
    vid = view_id.get("value", view_id) if isinstance(view_id, dict) else view_id
    periods = by_view.get(vid, [])
    option = _build_chart_option(periods)
    chart_el.options = option
    chart_el.update()


# ── Period table ──────────────────────────────────────────────────────────────

def _render_period_table(
    periods: list[ScorePeriod],
    show_benchmark_col: bool = True,
    is_macro: bool = False,
):
    """Render a table of score periods with returns and verdicts."""
    if not periods:
        ui.label("No score changes recorded yet.").style(
            "color:var(--text-muted); font-size:0.82rem; padding:1rem 0;"
        )
        return

    cols = "140px 80px 1fr 100px 40px" if show_benchmark_col else "140px 80px 1fr 40px"
    with ui.element("div").classes("attr-section").style("padding:0;"):
        with ui.element("div").classes("attr-hdr").style(f"grid-template-columns:{cols}; padding:0.3rem 0.75rem;"):
            ui.label("VIEW").style(
                "font-size:0.6rem; font-weight:700; color:var(--text-muted); letter-spacing:0.12em;"
            )
            ui.label("DIRECTION").style(
                "font-size:0.6rem; font-weight:700; color:var(--text-muted); letter-spacing:0.12em;"
            )
            ui.label("PERIOD").style(
                "font-size:0.6rem; font-weight:700; color:var(--text-muted); letter-spacing:0.12em;"
            )
            if show_benchmark_col:
                label = "INDICATOR" if is_macro else "RETURN"
                ui.label(label).style(
                    "font-size:0.6rem; font-weight:700; color:var(--text-muted); letter-spacing:0.12em;"
                )
            ui.label("").style("")  # verdict icon

        for p in periods:
            icon, icon_color = _verdict_html(p.verdict)

            # Return color based on whether the call was right
            if p.verdict == "good":
                ret_color = _GREEN
            elif p.verdict == "bad":
                ret_color = _RED
            else:
                ret_color = _MUTED

            # Row tint and left border
            tint = {"good": "#4ade8008", "bad": "#f8717108"}.get(p.verdict, "transparent")
            border_left = f"3px solid {icon_color}" if p.verdict in ("good", "bad") else "3px solid transparent"
            padding_fix = "calc(0.75rem - 3px)" if p.verdict in ("good", "bad") else "0.75rem"

            with ui.element("div").classes("attr-row").style(
                f"grid-template-columns:{cols}; background:{tint}; "
                f"border-left:{border_left}; padding-left:{padding_fix}; padding-right:0.75rem;"
            ):
                ui.label(p.view_name).style(
                    "font-size:0.78rem; color:var(--text-primary); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                )
                ui.label(p.score).style(
                    "font-size:0.78rem; color:var(--accent); font-weight:700;"
                )
                ui.label(_period_str(p.start_date, p.end_date)).style(
                    "font-size:0.75rem; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                )
                if show_benchmark_col:
                    if is_macro:
                        ui.label(p.benchmark_label).style(
                            "font-size:0.75rem; color:var(--text-muted);"
                        )
                    else:
                        ui.label(_ret_str(p.benchmark_return)).style(
                            f"font-size:0.78rem; color:{ret_color}; font-weight:700;"
                        )
                ui.label(icon).style(
                    f"font-size:1rem; color:{icon_color}; text-align:center; font-weight:700;"
                )


# ── Score analysis ────────────────────────────────────────────────────────────

def _render_score_analysis(analysis: list[ScoreAnalysis]):
    """Render the score-level analysis section."""
    if not any(a.period_count > 0 for a in analysis):
        return

    ui.label("SCORE ANALYSIS").classes("section-header").style("margin-top:1.5rem;")
    ui.label("Average benchmark return by score level").style(
        "color:var(--text-muted); font-size:0.75rem; margin-bottom:0.5rem;"
    )

    with ui.element("div").classes("attr-section").style("padding:0;"):
        with ui.element("div").classes("attr-hdr").style("grid-template-columns:180px 80px 1fr 80px; padding:0.3rem 0.75rem;"):
            for text in ["SCORE", "N", "AVG RETURN", ""]:
                ui.label(text).style(
                    "font-size:0.6rem; font-weight:700; color:var(--text-muted); letter-spacing:0.12em;"
                )

        for a in analysis:
            if a.period_count == 0:
                continue

            ret_str = f"{a.avg_return:+.1f}%" if a.avg_return is not None else "—"
            if a.avg_return is not None:
                ret_color = _GREEN if a.avg_return > 0 else _RED if a.avg_return < 0 else _MUTED
            else:
                ret_color = _MUTED

            # Bar visualization
            bar_width = min(abs(a.avg_return or 0) * 3, 100) if a.avg_return is not None else 0
            bar_color = _GREEN if (a.avg_return or 0) > 0 else _RED if (a.avg_return or 0) < 0 else _FAINT

            with ui.element("div").classes("attr-row").style("grid-template-columns:180px 80px 1fr 80px;"):
                ui.label(a.label).style("font-size:0.78rem; color:var(--text-primary);")
                ui.label(str(a.period_count)).style("font-size:0.78rem; color:var(--text-muted);")
                with ui.element("div").style("display:flex; align-items:center; gap:0.4rem;"):
                    if bar_width > 0:
                        ui.element("div").style(
                            f"width:{bar_width}px; height:6px; border-radius:3px; background:{bar_color};"
                        )
                    ui.label(ret_str).style(f"font-size:0.78rem; color:{ret_color}; font-weight:700;")
                ui.label("").style("")


# ── Streak badge ──────────────────────────────────────────────────────────────

def _render_streak_badge(summary: AttributionSummary):
    """Render a streak badge if there's a streak of 2+."""
    if summary.streak_count < 2:
        return
    color = _GREEN if summary.streak_type == "good" else _RED
    icon = "✓" if summary.streak_type == "good" else "✗"
    with ui.element("span").classes("attr-streak-badge").style(
        f"background:{color}15; color:{color}; border:1px solid {color}33;"
    ):
        ui.label(f"{icon} {summary.streak_count}× streak").style(
            f"font-size:0.72rem; font-weight:700; color:{color}; font-family:{_MONO};"
        )


# ── Empty state ───────────────────────────────────────────────────────────────

def _render_empty_state():
    ui.label("Not enough data yet.").style(
        "font-size:1rem; font-weight:700; color:var(--accent); margin-bottom:0.5rem;"
    )
    ui.label(
        "Attribution requires at least one score change recorded in daily snapshots. "
        "Keep tracking your views — data will appear here once you have score transitions."
    ).style("color:var(--text-muted); font-size:0.82rem; line-height:1.6; max-width:500px;")


# ── Main entry point ──────────────────────────────────────────────────────────

def render_attribution(state: AppState, fred_data: list | None):
    """Render the full Attribution tab."""
    _inject_css()

    fred_index = {ind.id: ind for ind in (fred_data or [])}

    ui.label("ATTRIBUTION").classes("section-header")
    ui.label("Were your views right? Score changes measured against benchmark returns.").style(
        "color:var(--text-muted); font-size:0.78rem; margin-bottom:1.25rem;"
    )

    # ── Compute attribution ───────────────────────────────────────────────
    asset_periods, asset_analysis, asset_summary = compute_asset_attribution(state)
    macro_periods, macro_summary = compute_macro_attribution(state, fred_index)

    has_data = asset_periods or macro_periods
    if not has_data:
        _render_empty_state()
        return

    # ── Summary cards ─────────────────────────────────────────────────────
    total_good = asset_summary.good + macro_summary.good
    total_bad = asset_summary.bad + macro_summary.bad
    total_scored = total_good + total_bad
    overall_hit = (total_good / total_scored * 100) if total_scored else None
    overall_streak = max(asset_summary.streak_count, macro_summary.streak_count)
    overall_streak_type = (
        asset_summary.streak_type if asset_summary.streak_count >= macro_summary.streak_count
        else macro_summary.streak_type
    )

    with ui.row().classes("w-full").style("gap:0.75rem; margin-bottom:1.5rem; flex-wrap:wrap; align-items:flex-start;"):
        _stat_card(
            f"{overall_hit:.0f}%" if overall_hit is not None else "—",
            "HIT RATE",
            _GREEN if (overall_hit or 0) >= 60 else _RED if (overall_hit or 0) < 40 else "var(--accent)",
        )
        _stat_card(f"{total_good}", "GOOD CALLS", _GREEN)
        _stat_card(f"{total_bad}", "BAD CALLS", _RED)
        _stat_card(
            f"{asset_summary.total_periods + macro_summary.total_periods}",
            "TOTAL PERIODS",
            "var(--accent)",
        )

        # Streak badge
        if overall_streak >= 2:
            streak_color = _GREEN if overall_streak_type == "good" else _RED
            streak_icon = "✓" if overall_streak_type == "good" else "✗"
            with ui.element("span").classes("attr-streak-badge").style(
                f"background:{streak_color}15; color:{streak_color}; border:1px solid {streak_color}33;"
            ):
                ui.label(f"{streak_icon} {overall_streak}× streak")

    # ── Benchmark chart ───────────────────────────────────────────────────
    if asset_periods:
        _render_attribution_chart(asset_periods)

    # ── Asset Views section ───────────────────────────────────────────────
    if asset_periods:
        ui.label("ASSET VIEWS").classes("section-header").style("margin-top:0.5rem;")
        if asset_summary.hit_rate is not None:
            ui.label(f"Hit rate: {asset_summary.hit_rate:.0f}%  ·  Weighted alpha: {asset_summary.total_alpha:+.1f}%").style(
                "color:var(--text-muted); font-size:0.75rem; margin-bottom:0.5rem;"
            )
        _render_period_table(asset_periods, show_benchmark_col=True, is_macro=False)
        _render_score_analysis(asset_analysis)

    # ── Macro Views section ───────────────────────────────────────────────
    if macro_periods:
        ui.label("MACRO VIEWS").classes("section-header").style("margin-top:1.5rem;")
        if macro_summary.hit_rate is not None:
            ui.label(f"Hit rate: {macro_summary.hit_rate:.0f}%").style(
                "color:var(--text-muted); font-size:0.75rem; margin-bottom:0.5rem;"
            )
        _render_period_table(macro_periods, show_benchmark_col=True, is_macro=True)

    # ── Legend ─────────────────────────────────────────────────────────────
    with ui.row().style("gap:1.5rem; margin-top:1.5rem; align-items:center;"):
        for icon, color, desc in [
            ("✓", _GREEN, "Good call — score direction matched benchmark"),
            ("✗", _RED, "Bad call — score direction contradicted benchmark"),
            ("—", _MUTED, "Neutral or insufficient data"),
        ]:
            with ui.row().style("gap:0.3rem; align-items:center;"):
                ui.label(icon).style(f"font-size:0.9rem; color:{color}; font-weight:700;")
                ui.label(desc).style("font-size:0.68rem; color:var(--text-muted);")
