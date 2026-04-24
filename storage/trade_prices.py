"""Fetch adjusted-close price series for trade tickers via yfinance.

Uses auto_adjust=True so the Close column reflects total return
(dividends + splits), which matters for bond ETFs like LQD/TLT.
"""
from __future__ import annotations
import logging
from datetime import date
import pandas as pd

logger = logging.getLogger(__name__)
_cache: dict = {}


def _key(trades) -> tuple:
    tickers = tuple(sorted({t.ticker.upper() for t in trades}))
    start = min(t.entry_date for t in trades)
    return (tickers, start, str(date.today()))


def invalidate() -> None:
    _cache.clear()


def fetch_trade_prices(trades) -> dict[str, pd.Series]:
    """Return {ticker: adj-close Series} for all tickers in trades list."""
    if not trades:
        return {}
    key = _key(trades)
    if key in _cache:
        return _cache[key]

    tickers = sorted({t.ticker.upper() for t in trades})
    start = min(t.entry_date for t in trades)
    result: dict[str, pd.Series] = {}

    try:
        import yfinance as yf
        raw = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
        if isinstance(raw, pd.Series):
            result[tickers[0]] = raw.dropna()
        else:
            for sym in tickers:
                result[sym] = raw[sym].dropna() if sym in raw.columns else pd.Series(dtype=float)
    except Exception as exc:
        logger.warning("trade_prices fetch failed: %s", exc)
        result = {sym: pd.Series(dtype=float) for sym in tickers}

    _cache[key] = result
    return result


def price_on_or_before(series: pd.Series, date_str: str) -> float | None:
    """Adj-close on date_str, or nearest prior trading day. None if before data starts."""
    if series is None or series.empty:
        return None
    try:
        cutoff = pd.Timestamp(date_str)
        eligible = series[series.index <= cutoff]
        return float(eligible.iloc[-1]) if not eligible.empty else None
    except Exception:
        return None
