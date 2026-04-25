"""Fetch price series for trade tickers via yfinance.

Downloads with auto_adjust=False to get both:
  - "Adj Close"  → dividend/split-adjusted series (total return proxy)
  - "Close"      → raw unadjusted close (price return only)

Ratio of adjusted prices gives total return; ratio of raw prices gives
price-only return. The difference is the income/carry component — significant
for bond ETFs (TLT, LQD, HYG, etc.) where yield is a large part of return.
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


def fetch_trade_prices(trades) -> dict[str, dict[str, pd.Series]]:
    """Return {ticker: {"total": adj-close Series, "price": raw-close Series}}."""
    if not trades:
        return {}
    key = _key(trades)
    if key in _cache:
        return _cache[key]

    tickers = sorted({t.ticker.upper() for t in trades})
    start = min(t.entry_date for t in trades)
    result: dict[str, dict[str, pd.Series]] = {}

    try:
        import yfinance as yf
        raw = yf.download(tickers, start=start, auto_adjust=False, progress=False)

        def _extract(field: str, sym: str) -> pd.Series:
            try:
                col = raw[field]
                if isinstance(col, pd.Series):
                    return col.dropna()
                return col[sym].dropna() if sym in col.columns else pd.Series(dtype=float)
            except Exception:
                return pd.Series(dtype=float)

        for sym in tickers:
            result[sym] = {
                "total": _extract("Adj Close", sym),
                "price": _extract("Close", sym),
            }
    except Exception as exc:
        logger.warning("trade_prices fetch failed: %s", exc)
        empty = {"total": pd.Series(dtype=float), "price": pd.Series(dtype=float)}
        result = {sym: dict(empty) for sym in tickers}

    _cache[key] = result
    return result


def price_on_or_before(series: pd.Series, date_str: str) -> float | None:
    """Price on date_str, or nearest prior trading day. None if before data starts."""
    if series is None or series.empty:
        return None
    try:
        cutoff = pd.Timestamp(date_str)
        eligible = series[series.index <= cutoff]
        return float(eligible.iloc[-1]) if not eligible.empty else None
    except Exception:
        return None
