"""View-vs-returns attribution engine.

Walks daily snapshots to find score-change periods, then computes benchmark
returns over each period. Produces per-asset and per-macro attribution with
hit-rate and alpha metrics.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"

# ── Benchmark mappings ────────────────────────────────────────────────────────

# Asset view id → benchmark ETF ticker (None = no proxy)
ASSET_BENCH: dict[str, Optional[str]] = {
    "stocks_bonds": "SPY",
    "eq_us_lc":     "SPY",
    "eq_us_smid":   "IWM",
    "eq_europe":    "EFA",
    "eq_japan":     "EWJ",
    "eq_em_xch":    "EEM",
    "eq_china":     "FXI",
    "eq_pe":        None,
    "fi_tsy":       "TLT",
    "fi_sec":       None,
    "fi_lev":       "HYG",
    "fi_global":    "BNDX",
    "fi_em":        "EMB",
}

# Macro view id → primary FRED indicator id (for directional attribution)
MACRO_BENCH: dict[str, str] = {
    "growth":        "gdp",
    "global_growth": "eem",
    "inflation":     "core_cpi",
    "fed":           "dgs2",
    "term_premium":  "dgs10",
    "credit":        "hy_oas",
    "usd":           "dxy",
}

# Short labels for macro indicators
_MACRO_SHORT: dict[str, str] = {
    "gdp":      "GDP",
    "eem":      "EEM",
    "core_cpi": "Core CPI",
    "dgs2":     "2Y Yield",
    "dgs10":    "10Y Yield",
    "hy_oas":   "HY OAS",
    "dxy":      "DXY",
}

# Macro direction → numeric sign for directional scoring
# Bullish on USD = expect DXY up (+1).  Bearish on credit (HY OAS) = expect OAS down (-1).
# For most indicators: Bullish = expect value up (+1).
# Exceptions where Bullish = expect value DOWN:
#   credit (HY OAS, IG OAS — tighter spreads = bullish)
_MACRO_DIR_SIGN: dict[str, int] = {
    "growth":        1,
    "global_growth": 1,
    "inflation":     1,   # Bullish inflation = expect higher CPI
    "fed":           1,   # Bullish fed = expect higher rates (hawkish)
    "term_premium":  1,
    "credit":       -1,   # Bullish credit = expect tighter spreads (lower OAS)
    "usd":           1,
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ScorePeriod:
    view_id: str
    view_name: str
    score: str
    start_date: date
    end_date: Optional[date]        # None = still active
    benchmark_return: Optional[float]
    verdict: str                    # "good" | "bad" | "neutral" | "n/a"
    benchmark_label: str            # ticker or indicator name
    chart_series: list = field(default_factory=list)  # [{"date": str, "value": float}]


@dataclass
class ScoreAnalysis:
    score: str
    label: str
    period_count: int
    avg_return: Optional[float]


@dataclass
class AttributionSummary:
    total_periods: int
    good: int
    bad: int
    neutral: int
    na: int
    hit_rate: Optional[float]       # good / (good + bad)
    total_alpha: float              # sum of weighted alpha
    streak_count: int = 0
    streak_type: str = ""           # "good" or "bad"


# ── Snapshot loading ──────────────────────────────────────────────────────────

def _load_timeline() -> list[tuple[date, dict[str, str], dict[str, str]]]:
    """Load snapshots and return sorted timeline.

    Each entry: (date, {asset_view_id: score}, {macro_view_id: direction})
    """
    snap_files = sorted(_SNAPSHOTS_DIR.glob("state_*.json"))
    timeline: list[tuple[date, dict[str, str], dict[str, str]]] = []
    for f in snap_files:
        try:
            snap_date = date.fromisoformat(f.stem.replace("state_", ""))
            data = json.loads(f.read_text(encoding="utf-8"))
            asset_scores = {av["id"]: av["direction"] for av in data.get("asset_views", [])}
            macro_scores = {mv["id"]: mv["direction"] for mv in data.get("macro_views", [])}
            timeline.append((snap_date, asset_scores, macro_scores))
        except Exception:
            continue
    return timeline


def _append_live_state(timeline, state) -> list[tuple[date, dict[str, str], dict[str, str]]]:
    """Append today's live state as the final entry."""
    today = date.today()
    asset_scores = {av.id: av.direction for av in state.asset_views}
    macro_scores = {mv.id: mv.direction for mv in state.macro_views}
    timeline.append((today, asset_scores, macro_scores))
    return timeline


# ── Period extraction ─────────────────────────────────────────────────────────

def _find_periods(
    timeline: list[tuple[date, dict[str, str], dict[str, str]]],
    view_id: str,
    kind: str,  # "asset" or "macro"
) -> list[tuple[str, date, Optional[date]]]:
    """Find contiguous score periods for a view.

    Returns list of (score, start_date, end_date).
    end_date is None if the period is still active (last entry).
    """
    idx = 1 if kind == "asset" else 2
    periods: list[tuple[str, date, Optional[date]]] = []

    if len(timeline) < 2:
        return periods

    # Start from the first snapshot
    current_score = timeline[0][idx].get(view_id, "—")
    current_start = timeline[0][0]

    def _skip(score: str) -> bool:
        return score in ("—", "No View")

    for i in range(1, len(timeline)):
        snap_date, asset_scores, macro_scores = timeline[i]
        scores = asset_scores if kind == "asset" else macro_scores
        score = scores.get(view_id, "—")

        if score != current_score:
            # Period ended
            if not _skip(current_score):
                periods.append((current_score, current_start, snap_date))
            current_score = score
            current_start = snap_date

    # Final period (still active or last)
    if not _skip(current_score):
        periods.append((current_score, current_start, None))

    return periods


# ── Price lookup helpers ──────────────────────────────────────────────────────

def _price_on_or_before(series: pd.Series, d: date) -> Optional[float]:
    """Get price on or nearest prior trading day."""
    if series is None or series.empty:
        return None
    try:
        cutoff = pd.Timestamp(d)
        eligible = series[series.index <= cutoff]
        return float(eligible.iloc[-1]) if not eligible.empty else None
    except Exception:
        return None


def _fred_value_on_or_before(chart_series: list[dict], d: date) -> Optional[float]:
    """Get FRED indicator value on or nearest prior date from chart_series."""
    if not chart_series:
        return None
    cutoff = d.isoformat()
    best = None
    for entry in chart_series:
        if entry["date"] <= cutoff:
            best = entry["value"]
        else:
            break
    return best


# ── Benchmark data fetching ──────────────────────────────────────────────────

_price_cache: dict = {}


def fetch_benchmark_prices(tickers: list[str], start: str) -> dict[str, pd.Series]:
    """Fetch adjusted-close price series for benchmark tickers via yfinance.

    Returns {ticker: pd.Series} with DatetimeIndex.
    """
    if not tickers:
        return {}

    key = (tuple(sorted(tickers)), start, str(date.today()))
    if key in _price_cache:
        return _price_cache[key]

    result: dict[str, pd.Series] = {}
    try:
        import yfinance as yf
        raw = yf.download(tickers, start=start, auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            close_col = raw["Close"]
            for sym in tickers:
                if sym in close_col.columns:
                    result[sym] = close_col[sym].dropna()
                else:
                    result[sym] = pd.Series(dtype=float)
        else:
            # Single ticker
            if len(tickers) == 1:
                result[tickers[0]] = raw["Close"].dropna() if "Close" in raw.columns else pd.Series(dtype=float)
    except Exception as exc:
        logger.warning("Benchmark price fetch failed: %s", exc)
        for sym in tickers:
            result[sym] = pd.Series(dtype=float)

    _price_cache[key] = result
    return result


# ── Attribution computation ───────────────────────────────────────────────────

def _compute_verdict(score: str, return_pct: Optional[float]) -> str:
    """Determine if a score + return pair was a good call."""
    if return_pct is None:
        return "n/a"
    try:
        s = int(score)
    except (ValueError, TypeError):
        return "n/a"
    if s == 3:
        return "neutral"
    alpha = (s - 3) * return_pct
    if alpha > 0:
        return "good"
    if alpha < 0:
        return "bad"
    return "neutral"


def _compute_macro_verdict(
    direction: str,
    start_val: Optional[float],
    end_val: Optional[float],
    dir_sign: int,
) -> str:
    """Determine if a macro view call was correct.

    dir_sign: +1 means Bullish = expect value up, -1 means Bullish = expect value down.
    """
    if start_val is None or end_val is None or start_val == 0:
        return "n/a"
    if direction == "No View":
        return "n/a"
    if direction == "Neutral":
        return "neutral"

    change = end_val - start_val
    direction_sign = {"Bullish": 1, "Bearish": -1}.get(direction, 0)
    if direction_sign == 0:
        return "n/a"

    # Effective signal: direction_sign * dir_sign (accounts for inverted indicators)
    effective = direction_sign * dir_sign
    if effective * change > 0:
        return "good"
    if effective * change < 0:
        return "bad"
    return "neutral"


def _compute_streak(periods: list[ScorePeriod]) -> tuple[int, str]:
    """Return (streak_count, streak_type) for the most recent consecutive streak.

    Walks periods in reverse chronological order (newest first).
    Returns (0, "") if no streak.
    """
    scored = sorted(
        [p for p in periods if p.verdict in ("good", "bad")],
        key=lambda p: p.start_date,
        reverse=True,
    )
    if not scored:
        return 0, ""
    streak_type = scored[0].verdict
    count = 0
    for p in scored:
        if p.verdict == streak_type:
            count += 1
        else:
            break
    return count, streak_type


def compute_asset_attribution(state) -> tuple[list[ScorePeriod], list[ScoreAnalysis], AttributionSummary]:
    """Compute attribution for all asset views with benchmarks."""
    timeline = _load_timeline()
    if not timeline:
        return [], [], AttributionSummary(0, 0, 0, 0, 0, None, 0.0)

    timeline = _append_live_state(timeline, state)

    # Determine start date for price fetch
    start_str = timeline[0][0].isoformat()

    # Collect unique tickers we need
    tickers_needed = sorted({t for t in ASSET_BENCH.values() if t})
    prices = fetch_benchmark_prices(tickers_needed, start_str)

    periods: list[ScorePeriod] = []
    # Pre-build chart series per ticker
    chart_by_ticker: dict[str, list[dict]] = {}
    for ticker in tickers_needed:
        series = prices.get(ticker, pd.Series(dtype=float))
        if not series.empty:
            chart_by_ticker[ticker] = [
                {"date": d.strftime("%Y-%m-%d"), "value": round(float(v), 2)}
                for d, v in zip(series.index, series.values)
            ]

    for av in state.asset_views:
        ticker = ASSET_BENCH.get(av.id)
        if not ticker:
            continue

        score_periods = _find_periods(timeline, av.id, "asset")
        series = prices.get(ticker, pd.Series(dtype=float))
        chart_data = chart_by_ticker.get(ticker, [])

        for score, start_d, end_d in score_periods:
            p_start = _price_on_or_before(series, start_d)
            p_end = _price_on_or_before(series, end_d) if end_d else _price_on_or_before(series, date.today())

            ret = None
            if p_start and p_end and p_start != 0:
                ret = (p_end / p_start - 1) * 100

            verdict = _compute_verdict(score, ret)
            periods.append(ScorePeriod(
                view_id=av.id,
                view_name=av.name,
                score=score,
                start_date=start_d,
                end_date=end_d,
                benchmark_return=ret,
                verdict=verdict,
                benchmark_label=ticker,
                chart_series=chart_data,
            ))

    # Score analysis
    score_labels = {"1": "1 — Strong UW", "2": "2 — UW", "3": "3 — Neutral", "4": "4 — OW", "5": "5 — Strong OW"}
    analysis: list[ScoreAnalysis] = []
    for s in ["1", "2", "3", "4", "5"]:
        matching = [p for p in periods if p.score == s and p.benchmark_return is not None]
        avg_ret = (sum(p.benchmark_return for p in matching) / len(matching)) if matching else None
        analysis.append(ScoreAnalysis(score=s, label=score_labels[s], period_count=len(matching), avg_return=avg_ret))

    # Summary
    scored = [p for p in periods if p.verdict in ("good", "bad")]
    streak_count, streak_type = _compute_streak(periods)
    summary = AttributionSummary(
        total_periods=len(periods),
        good=sum(1 for p in periods if p.verdict == "good"),
        bad=sum(1 for p in periods if p.verdict == "bad"),
        neutral=sum(1 for p in periods if p.verdict == "neutral"),
        na=sum(1 for p in periods if p.verdict == "n/a"),
        hit_rate=(sum(1 for p in scored if p.verdict == "good") / len(scored) * 100) if scored else None,
        total_alpha=sum(
            (int(p.score) - 3) * (p.benchmark_return or 0) for p in periods
            if p.benchmark_return is not None and p.score in ("1", "2", "3", "4", "5")
        ),
        streak_count=streak_count,
        streak_type=streak_type,
    )

    return periods, analysis, summary


def compute_macro_attribution(state, fred_index: dict) -> tuple[list[ScorePeriod], AttributionSummary]:
    """Compute attribution for all macro views using FRED indicator data."""
    timeline = _load_timeline()
    if not timeline:
        return [], AttributionSummary(0, 0, 0, 0, 0, None, 0.0)

    timeline = _append_live_state(timeline, state)

    periods: list[ScorePeriod] = []
    for mv in state.macro_views:
        indicator_id = MACRO_BENCH.get(mv.id)
        if not indicator_id:
            continue

        ind = fred_index.get(indicator_id)
        if not ind or ind.error:
            continue

        chart = ind.chart_series or []
        if not chart:
            continue

        dir_sign = _MACRO_DIR_SIGN.get(mv.id, 1)
        score_periods = _find_periods(timeline, mv.id, "macro")

        for direction, start_d, end_d in score_periods:
            val_start = _fred_value_on_or_before(chart, start_d)
            val_end = _fred_value_on_or_before(chart, end_d) if end_d else _fred_value_on_or_before(chart, date.today())

            ret = None
            if val_start is not None and val_end is not None and val_start != 0:
                ret = (val_end - val_start) / abs(val_start) * 100

            verdict = _compute_macro_verdict(direction, val_start, val_end, dir_sign)
            periods.append(ScorePeriod(
                view_id=mv.id,
                view_name=mv.name,
                score=direction,
                start_date=start_d,
                end_date=end_d,
                benchmark_return=ret,
                verdict=verdict,
                benchmark_label=_MACRO_SHORT.get(indicator_id, indicator_id),
            ))

    scored = [p for p in periods if p.verdict in ("good", "bad")]
    streak_count, streak_type = _compute_streak(periods)
    summary = AttributionSummary(
        total_periods=len(periods),
        good=sum(1 for p in periods if p.verdict == "good"),
        bad=sum(1 for p in periods if p.verdict == "bad"),
        neutral=sum(1 for p in periods if p.verdict == "neutral"),
        na=sum(1 for p in periods if p.verdict == "n/a"),
        hit_rate=(sum(1 for p in scored if p.verdict == "good") / len(scored) * 100) if scored else None,
        total_alpha=0.0,  # Not meaningful for macro (different units per indicator)
        streak_count=streak_count,
        streak_type=streak_type,
    )

    return periods, summary
