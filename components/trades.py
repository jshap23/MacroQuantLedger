"""Trade Tracker tab — log ETF positions and track total-return performance."""
from __future__ import annotations
import asyncio
from datetime import date, datetime
from nicegui import ui, run
from models.schema import AppState, Trade
from storage.persistence import save_state
from storage import trade_prices

_DATE_FMT = "%Y-%m-%d"
_TICKER_CLR = "#2dd4bf"

# Grid column templates
_OPEN_COLS = "85px 92px 52px 82px 82px 68px 76px 80px 1fr 62px 34px"
_CLOSED_COLS = "85px 92px 92px 52px 82px 82px 68px 76px 80px 1fr 34px"
_ROW_STYLE = (
    "display:grid; align-items:center; gap:0.5rem; padding:0.42rem 0.75rem; "
    "border-bottom:1px solid var(--border);"
)
_HDR_STYLE = (
    "display:grid; align-items:center; gap:0.5rem; padding:0.28rem 0.75rem; "
    "border-bottom:1px solid var(--border-strong); background:var(--bg-status);"
    "border-radius:6px 6px 0 0;"
)


# ── formatting helpers ────────────────────────────────────────────────────────

def _fmt_px(v: float | None) -> str:
    return f"${v:.2f}" if v is not None else "—"


def _fmt_ret(entry: float | None, current: float | None) -> tuple[str, str]:
    if entry is None or current is None or entry == 0:
        return "—", "var(--text-muted)"
    pct = (current / entry - 1) * 100
    sign = "+" if pct >= 0 else ""
    color = "#4ade80" if pct >= 0 else "#f87171"
    return f"{sign}{pct:.2f}%", color


def _fmt_pnl(entry: float | None, current: float | None, size: float | None) -> tuple[str, str]:
    if entry is None or current is None or size is None or entry == 0:
        return "—", "var(--text-muted)"
    pnl = size * (current / entry - 1)
    sign = "+" if pnl >= 0 else ""
    color = "#4ade80" if pnl >= 0 else "#f87171"
    return f"{sign}${pnl:,.0f}", color


def _days_held(entry_date: str, exit_date: str | None) -> str:
    try:
        s = datetime.strptime(entry_date, _DATE_FMT).date()
        e = datetime.strptime(exit_date, _DATE_FMT).date() if exit_date else date.today()
        return f"{(e - s).days}d"
    except Exception:
        return "—"


# ── primitive UI helpers ──────────────────────────────────────────────────────

def _hdr(text: str):
    ui.label(text).style(
        "font-size:0.6rem; font-weight:700; color:var(--text-muted); "
        "letter-spacing:0.12em; font-family:'IBM Plex Mono',monospace;"
    )


def _cell(text: str, color: str = "var(--text-primary)", bold: bool = False):
    ui.label(text).style(
        f"font-size:0.81rem; color:{color}; font-weight:{'700' if bold else '400'}; "
        "font-family:'IBM Plex Mono',monospace; overflow:hidden; "
        "text-overflow:ellipsis; white-space:nowrap;"
    )


# ── main entry point ──────────────────────────────────────────────────────────

def render_trades(state: AppState, save_indicator):
    container = ui.element("div").style("width:100%;")

    def save_fn():
        save_state(state)
        save_indicator()

    async def reload():
        prices = await run.io_bound(trade_prices.fetch_trade_prices, state.trades)
        container.clear()
        with container:
            _add_form(state, save_fn, reload)
            _open_section(state, prices, save_fn, reload)
            _closed_section(state, prices, save_fn, reload)
            _footnote()

    with container:
        if state.trades:
            with ui.column().style("align-items:center; padding:3rem; gap:0.75rem;"):
                ui.spinner("audio", size="1.5rem", color="#2dd4bf")
                ui.label("Fetching prices…").style(
                    "color:var(--text-muted); font-size:0.8rem; "
                    "font-family:'IBM Plex Mono',monospace;"
                )
        else:
            _add_form(state, save_fn, reload)
            _open_section(state, {}, save_fn, reload)
            _closed_section(state, {}, save_fn, reload)
            _footnote()

    if state.trades:
        asyncio.ensure_future(reload())


def _footnote():
    with ui.element("div").style("margin-top:2rem; padding-top:1rem; border-top:1px solid var(--border);"):
        ui.html(
            "<span style='"
            "font-size:0.67rem; color:var(--text-faint); "
            "font-family:\"IBM Plex Mono\",monospace; line-height:1.7; letter-spacing:0.02em;"
            "'>"
            "<b>PRICE RTN</b> — raw unadjusted close (entry → current/exit). Capital gains only, no income. "
            "This is the price you see on a chart.<br>"
            "<b>TOTAL RTN</b> — dividend-adjusted close via yfinance (Adj Close). "
            "Includes reinvested dividends and distributions. Bold because it's the economically correct return.<br>"
            "<b>P&amp;L</b> — notional × total return. Only meaningful when Size $ was set at entry.<br>"
            "<b>Carry</b> — not shown explicitly; implied as Total RTN − Price RTN. "
            "Especially material for bond ETFs (TLT ~4%, LQD ~5%, HYG ~7% annualised yield)."
            "</span>"
        )


# ── add-position form ─────────────────────────────────────────────────────────

def _add_form(state: AppState, save_fn, reload):
    with ui.element("div").style(
        "background:var(--bg-card); border:1px solid var(--border-strong); "
        "border-radius:6px; padding:1rem 1.1rem; margin-bottom:1.5rem; width:100%;"
    ):
        ui.label("ADD POSITION").classes("section-header")
        with ui.row().style("gap:0.75rem; align-items:flex-end; flex-wrap:wrap; width:100%;"):
            ticker_in = ui.input("Ticker", value="").style("min-width:90px; max-width:110px;").classes("dark-input")
            date_in   = ui.input("Entry Date", value=str(date.today())).style("min-width:150px; max-width:175px;").classes("dark-input")
            size_in   = ui.input("Size $ (opt.)", value="").style("min-width:120px; max-width:145px;").classes("dark-input")
            note_in   = ui.input("Note / thesis", value="").style("min-width:200px; flex:1;").classes("dark-input")

            def do_add():
                ticker = ticker_in.value.strip().upper()
                if not ticker:
                    ui.notify("Ticker is required", type="warning", position="top")
                    return
                try:
                    datetime.strptime(date_in.value.strip(), _DATE_FMT)
                except ValueError:
                    ui.notify("Date must be YYYY-MM-DD", type="warning", position="top")
                    return
                size: float | None = None
                raw_size = size_in.value.strip().replace("$", "").replace(",", "")
                if raw_size:
                    try:
                        size = float(raw_size)
                    except ValueError:
                        ui.notify("Invalid size — enter a number", type="warning", position="top")
                        return
                state.trades.append(Trade(
                    ticker=ticker,
                    entry_date=date_in.value.strip(),
                    size=size,
                    note=note_in.value.strip(),
                ))
                trade_prices.invalidate()
                save_fn()
                asyncio.ensure_future(reload())

            ui.button("Add", on_click=do_add).classes("submit-btn")


# ── open positions ────────────────────────────────────────────────────────────

def _open_section(state: AppState, prices: dict, save_fn, reload):
    open_trades = sorted(
        [t for t in state.trades if t.exit_date is None],
        key=lambda t: t.entry_date, reverse=True,
    )
    ui.label("OPEN POSITIONS").classes("section-header").style("margin-top:0.5rem;")
    if not open_trades:
        ui.label("No open positions.").style(
            "color:var(--text-faint); font-size:0.82rem; font-style:italic; padding:0.75rem 0;"
        )
        return

    with ui.element("div").style(
        "background:var(--bg-card); border:1px solid var(--border); "
        "border-radius:6px; overflow:hidden;"
    ):
        with ui.element("div").style(f"{_HDR_STYLE} grid-template-columns:{_OPEN_COLS};"):
            for h in ["TICKER", "ENTERED", "DAYS", "ENTRY PX", "CURR PX", "PRICE RTN", "TOTAL RTN", "P&L", "NOTE", "", ""]:
                _hdr(h)
        for trade in open_trades:
            _open_row(state, trade, prices, save_fn, reload)


def _open_row(state: AppState, trade: Trade, prices: dict, save_fn, reload):
    data = prices.get(trade.ticker.upper()) or {}
    px_series  = data.get("price")
    tot_series = data.get("total")
    entry_raw  = trade_prices.price_on_or_before(px_series,  trade.entry_date) if px_series  is not None else None
    curr_raw   = float(px_series.iloc[-1])  if (px_series  is not None and not px_series.empty)  else None
    entry_adj  = trade_prices.price_on_or_before(tot_series, trade.entry_date) if tot_series is not None else None
    curr_adj   = float(tot_series.iloc[-1]) if (tot_series is not None and not tot_series.empty) else None
    px_ret_t,  px_ret_c  = _fmt_ret(entry_raw, curr_raw)
    tot_ret_t, tot_ret_c = _fmt_ret(entry_adj, curr_adj)
    pnl_t, pnl_c = _fmt_pnl(entry_adj, curr_adj, trade.size)
    note_s = (trade.note[:38] + "…") if len(trade.note) > 38 else trade.note

    with ui.element("div").style(f"{_ROW_STYLE} grid-template-columns:{_OPEN_COLS};"):
        ui.label(trade.ticker.upper()).style(
            f"font-size:0.88rem; font-weight:700; color:{_TICKER_CLR}; "
            "font-family:'IBM Plex Mono',monospace; letter-spacing:0.05em;"
        )
        _cell(trade.entry_date, color="var(--text-muted)")
        _cell(_days_held(trade.entry_date, None), color="var(--text-muted)")
        _cell(_fmt_px(entry_raw))
        _cell(_fmt_px(curr_raw))
        _cell(px_ret_t,  color=px_ret_c)
        _cell(tot_ret_t, color=tot_ret_c, bold=True)
        _cell(pnl_t, color=pnl_c)
        _cell(note_s, color="var(--text-faint)")

        def make_close(t=trade):
            def _go(): _close_dialog(t, save_fn, reload)
            return _go

        ui.button("Close", on_click=make_close()).style(
            "background:transparent; color:var(--text-muted); border:1px solid var(--border); "
            "font-family:'IBM Plex Mono',monospace; font-size:0.68rem; padding:2px 8px; "
            "border-radius:3px; box-shadow:none; min-height:unset;"
        )

        def make_del(t=trade):
            def _go():
                state.trades = [x for x in state.trades if x.id != t.id]
                trade_prices.invalidate()
                save_fn()
                asyncio.ensure_future(reload())
            return _go

        ui.button("✕", on_click=make_del()).style(
            "background:transparent; color:var(--text-faint); font-size:0.8rem; "
            "padding:2px 6px; min-height:unset; border-radius:3px; box-shadow:none; border:none;"
        )


# ── closed positions ──────────────────────────────────────────────────────────

def _closed_section(state: AppState, prices: dict, save_fn, reload):
    closed_trades = sorted(
        [t for t in state.trades if t.exit_date is not None],
        key=lambda t: t.exit_date, reverse=True,
    )
    ui.label("CLOSED POSITIONS").classes("section-header").style("margin-top:2rem;")
    if not closed_trades:
        ui.label("No closed positions.").style(
            "color:var(--text-faint); font-size:0.82rem; font-style:italic; padding:0.75rem 0;"
        )
        return

    with ui.element("div").style(
        "background:var(--bg-card); border:1px solid var(--border); "
        "border-radius:6px; overflow:hidden;"
    ):
        with ui.element("div").style(f"{_HDR_STYLE} grid-template-columns:{_CLOSED_COLS};"):
            for h in ["TICKER", "ENTERED", "EXITED", "DAYS", "ENTRY PX", "EXIT PX", "PRICE RTN", "TOTAL RTN", "P&L", "NOTE", ""]:
                _hdr(h)
        for trade in closed_trades:
            _closed_row(state, trade, prices, save_fn, reload)


def _closed_row(state: AppState, trade: Trade, prices: dict, save_fn, reload):
    data = prices.get(trade.ticker.upper()) or {}
    px_series  = data.get("price")
    tot_series = data.get("total")
    entry_raw = trade_prices.price_on_or_before(px_series,  trade.entry_date) if px_series  is not None else None
    exit_raw  = trade_prices.price_on_or_before(px_series,  trade.exit_date)  if px_series  is not None else None
    entry_adj = trade_prices.price_on_or_before(tot_series, trade.entry_date) if tot_series is not None else None
    exit_adj  = trade_prices.price_on_or_before(tot_series, trade.exit_date)  if tot_series is not None else None
    px_ret_t,  px_ret_c  = _fmt_ret(entry_raw, exit_raw)
    tot_ret_t, tot_ret_c = _fmt_ret(entry_adj, exit_adj)
    pnl_t, pnl_c = _fmt_pnl(entry_adj, exit_adj, trade.size)
    note_s = (trade.note[:38] + "…") if len(trade.note) > 38 else trade.note

    with ui.element("div").style(f"{_ROW_STYLE} grid-template-columns:{_CLOSED_COLS};"):
        ui.label(trade.ticker.upper()).style(
            "font-size:0.88rem; font-weight:700; color:var(--text-muted); "
            "font-family:'IBM Plex Mono',monospace; letter-spacing:0.05em;"
        )
        _cell(trade.entry_date, color="var(--text-muted)")
        _cell(trade.exit_date,  color="var(--text-muted)")
        _cell(_days_held(trade.entry_date, trade.exit_date), color="var(--text-muted)")
        _cell(_fmt_px(entry_raw))
        _cell(_fmt_px(exit_raw))
        _cell(px_ret_t,  color=px_ret_c)
        _cell(tot_ret_t, color=tot_ret_c, bold=True)
        _cell(pnl_t, color=pnl_c)
        _cell(note_s, color="var(--text-faint)")

        def make_del(t=trade):
            def _go():
                state.trades = [x for x in state.trades if x.id != t.id]
                trade_prices.invalidate()
                save_fn()
                asyncio.ensure_future(reload())
            return _go

        ui.button("✕", on_click=make_del()).style(
            "background:transparent; color:var(--text-faint); font-size:0.8rem; "
            "padding:2px 6px; min-height:unset; border-radius:3px; box-shadow:none; border:none;"
        )


# ── close-position dialog ─────────────────────────────────────────────────────

def _close_dialog(trade: Trade, save_fn, reload):
    with ui.dialog() as dialog, ui.card().style(
        "background:var(--bg-card); color:var(--text-primary); "
        "font-family:'IBM Plex Mono',monospace; min-width:min(320px,90vw); padding:1.5rem;"
    ):
        ui.label(f"Close {trade.ticker.upper()}").style(
            "font-size:1rem; font-weight:700; color:var(--accent); margin-bottom:0.5rem;"
        )
        ui.label(
            "Adj-close on exit date will be used (total return incl. dividends)."
        ).style("color:var(--text-muted); font-size:0.78rem; margin-bottom:0.75rem; line-height:1.5;")
        exit_in = ui.input("Exit Date (YYYY-MM-DD)", value=str(date.today())).classes("dark-input w-full")

        with ui.row().style("gap:0.5rem; justify-content:flex-end; margin-top:1rem;"):
            ui.button("Cancel", on_click=dialog.close).classes("cancel-btn")

            def confirm():
                try:
                    datetime.strptime(exit_in.value.strip(), _DATE_FMT)
                except ValueError:
                    ui.notify("Date must be YYYY-MM-DD", type="warning", position="top")
                    return
                trade.exit_date = exit_in.value.strip()
                trade_prices.invalidate()
                save_fn()
                dialog.close()
                asyncio.ensure_future(reload())

            ui.button("Close Position", on_click=confirm).classes("submit-btn")

    dialog.open()
