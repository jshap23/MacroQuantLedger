"""FRED API client — fetches and transforms macro indicators."""

import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import requests

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_BASE = "https://finnhub.io/api/v1"
logger = logging.getLogger(__name__)


@dataclass
class Indicator:
    id: str
    name: str
    group: str
    as_of: str
    value_label: str
    d3m_label: str
    d6m_label: str
    d12m_label: str
    d3m_color: str
    d6m_color: str
    d12m_color: str
    col_headers: tuple = ("3M", "6M", "12M")
    error: bool = False
    chart_series: list = field(default_factory=list)   # [{"date": str, "value": float}] ascending
    chart_label: str = ""


GROUPS = [
    "Labor",
    "Activity",
    "Inflation",
    "Rates & Curve",
    "Credit",
    "Risk & Markets",
    "Equities",
    "FX & Commodities",
]

# Colors
_GREEN   = "#4ade80"
_RED     = "#f87171"
_NEUTRAL = "#9090b0"
_FAINT   = "#505068"


# ── Color helpers ─────────────────────────────────────────────────────────────

def _csign(v: Optional[float], pos_good: int) -> str:
    if v is None:
        return _FAINT
    if pos_good == 0 or v == 0:
        return _NEUTRAL
    return (_GREEN if v > 0 else _RED) if pos_good == 1 else (_RED if v > 0 else _GREEN)


def _caccel(v: Optional[float], baseline: Optional[float]) -> str:
    """Green if decelerating vs baseline, red if accelerating."""
    if v is None or baseline is None:
        return _FAINT
    if v < baseline - 0.1:
        return _GREEN
    if v > baseline + 0.1:
        return _RED
    return _NEUTRAL


# ── Raw fetch ─────────────────────────────────────────────────────────────────

def _fetch(series_id: str, limit: int = 400, retries: int = 3) -> list:
    if not FRED_API_KEY:
        return []
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    for attempt in range(retries):
        try:
            r = requests.get(FRED_BASE, params=params, timeout=15)
            r.raise_for_status()
            return [
                {"date": o["date"], "value": float(o["value"])}
                for o in r.json().get("observations", [])
                if o["value"] != "."
            ]
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (500, 502, 503, 504) and attempt < retries - 1:
                wait = 2 ** attempt  # 1s, 2s
                logger.debug("FRED [%s]: %s — retrying in %ds (attempt %d/%d)",
                             series_id, e, wait, attempt + 1, retries)
                time.sleep(wait)
                continue
            logger.warning("FRED [%s]: %s", series_id, e)
            return []
        except Exception as e:
            logger.warning("FRED [%s]: %s", series_id, e)
            return []
    return []


# ── Observation helpers ───────────────────────────────────────────────────────

def _v(obs: list, n: int) -> Optional[float]:
    return obs[n]["value"] if len(obs) > n else None


def _at(obs: list, days: int) -> Optional[float]:
    if not obs:
        return None
    cutoff = datetime.strptime(obs[0]["date"], "%Y-%m-%d") - timedelta(days=days)
    for o in obs:
        if datetime.strptime(o["date"], "%Y-%m-%d") <= cutoff:
            return o["value"]
    return None


def _diff(a: Optional[float], b: Optional[float], scale: float = 1.0) -> Optional[float]:
    return (a - b) * scale if a is not None and b is not None else None


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100


def _ann(v0: Optional[float], vn: Optional[float], n: int, ppy: int = 12) -> Optional[float]:
    """Annualized % rate over n periods (ppy = periods per year)."""
    if v0 is None or vn is None or vn <= 0:
        return None
    return (math.pow(v0 / vn, ppy / n) - 1) * 100


def _fmt(v: Optional[float], fmt: str, na: str = "N/A") -> str:
    return na if v is None else fmt.format(v)


def _err(id, name, group, col_headers=("3M", "6M", "12M")) -> Indicator:
    return Indicator(
        id=id, name=name, group=group, as_of="N/A",
        value_label="N/A",
        d3m_label="—", d6m_label="—", d12m_label="—",
        d3m_color=_FAINT, d6m_color=_FAINT, d12m_color=_FAINT,
        col_headers=col_headers, error=True,
    )


# ── Chart data helpers ────────────────────────────────────────────────────────

def _chart_raw(obs: list) -> list:
    """Raw values in ascending date order."""
    return [{"date": o["date"], "value": round(o["value"], 5)} for o in reversed(obs)]


def _chart_yoy(obs: list) -> list:
    """12m YoY % computed from index level, ascending date order (monthly data)."""
    result = []
    for i in range(len(obs) - 12):
        base = obs[i + 12]["value"]
        if base and base > 0:
            yoy = (obs[i]["value"] / base - 1) * 100
            result.append({"date": obs[i]["date"], "value": round(yoy, 3)})
    return list(reversed(result))


def _chart_spread(obs_l: list, obs_s: list) -> list:
    """Spread (obs_l − obs_s) in bps, ascending date order."""
    s_map = {o["date"]: o["value"] for o in obs_s}
    result = []
    for o in reversed(obs_l):
        if o["date"] in s_map:
            result.append({"date": o["date"], "value": round((o["value"] - s_map[o["date"]]) * 100, 2)})
    return result


def _chart_mom(obs: list) -> list:
    """Month-over-month absolute difference, ascending date order."""
    result = []
    for i in range(len(obs) - 1):
        result.append({"date": obs[i]["date"], "value": round(obs[i]["value"] - obs[i + 1]["value"], 2)})
    return list(reversed(result))


def _chart_ratio(obs_n: list, obs_d: list) -> list:
    """Ratio n/d, ascending date order."""
    d_map = {o["date"]: o["value"] for o in obs_d}
    result = []
    for o in reversed(obs_n):
        if o["date"] in d_map and d_map[o["date"]]:
            result.append({"date": o["date"], "value": round(o["value"] / d_map[o["date"]], 4)})
    return result


# ── Transform: yields / rates (level %, changes in bps) ──────────────────────

def _rate_bps(obs: list, id: str, name: str, group: str, pos_good: int = 0) -> Indicator:
    if not obs:
        return _err(id, name, group)
    v0 = _v(obs, 0)
    d3 = _diff(v0, _at(obs, 91),  100)
    d6 = _diff(v0, _at(obs, 182), 100)
    d12= _diff(v0, _at(obs, 365), 100)
    return Indicator(
        id=id, name=name, group=group, as_of=obs[0]["date"],
        value_label=_fmt(v0, "{:.2f}"),
        d3m_label=_fmt(d3,  "{:+.0f}"), d3m_color=_csign(d3,  pos_good),
        d6m_label=_fmt(d6,  "{:+.0f}"), d6m_color=_csign(d6,  pos_good),
        d12m_label=_fmt(d12, "{:+.0f}"), d12m_color=_csign(d12, pos_good),
    )


# ── Transform: computed spread from two daily rate series ────────────────────

def _spread_bps(obs_l: list, obs_s: list, id: str, name: str, group: str,
                pos_good: int = 0) -> Indicator:
    if not obs_l or not obs_s:
        return _err(id, name, group)
    vl0, vs0 = _v(obs_l, 0), _v(obs_s, 0)
    if vl0 is None or vs0 is None:
        return _err(id, name, group)

    def spread_at(days):
        vl = _at(obs_l, days)
        vs = _at(obs_s, days)
        return _diff(vl, vs, 100) if vl is not None and vs is not None else None

    s0  = (vl0 - vs0) * 100
    d3  = _diff(s0, spread_at(91))
    d6  = _diff(s0, spread_at(182))
    d12 = _diff(s0, spread_at(365))
    return Indicator(
        id=id, name=name, group=group, as_of=obs_l[0]["date"],
        value_label=_fmt(s0, "{:+.0f}"),
        d3m_label=_fmt(d3,  "{:+.0f}"), d3m_color=_csign(d3,  pos_good),
        d6m_label=_fmt(d6,  "{:+.0f}"), d6m_color=_csign(d6,  pos_good),
        d12m_label=_fmt(d12, "{:+.0f}"), d12m_color=_csign(d12, pos_good),
    )


# ── Transform: % change (FX, commodities, equities) ─────────────────────────

def _pct_chg(obs: list, id: str, name: str, group: str,
              pos_good: int = 0, value_fmt: str = "{:.2f}") -> Indicator:
    if not obs:
        return _err(id, name, group)
    v0 = _v(obs, 0)
    d3  = _pct(v0, _at(obs, 91))
    d6  = _pct(v0, _at(obs, 182))
    d12 = _pct(v0, _at(obs, 365))
    return Indicator(
        id=id, name=name, group=group, as_of=obs[0]["date"],
        value_label=_fmt(v0, value_fmt),
        d3m_label=_fmt(d3,  "{:+.1f}"), d3m_color=_csign(d3,  pos_good),
        d6m_label=_fmt(d6,  "{:+.1f}"), d6m_color=_csign(d6,  pos_good),
        d12m_label=_fmt(d12, "{:+.1f}"), d12m_color=_csign(d12, pos_good),
    )


# ── Transform: inflation index → annualized rates ────────────────────────────

def _infl_ann(obs: list, id: str, name: str, group: str) -> Indicator:
    col_headers = ("3M Ann", "6M Ann", "12M YoY")
    if not obs or len(obs) < 13:
        return _err(id, name, group, col_headers)
    v0  = _v(obs, 0)
    yoy = _ann(v0, _v(obs, 12), 12, 12)   # simple YoY
    a3  = _ann(v0, _v(obs, 3),   3, 12)   # 3m annualized
    a6  = _ann(v0, _v(obs, 6),   6, 12)   # 6m annualized
    return Indicator(
        id=id, name=name, group=group, as_of=obs[0]["date"],
        value_label=_fmt(yoy, "{:.2f}"),
        d3m_label=_fmt(a3,  "{:.2f}"), d3m_color=_caccel(a3,  yoy),
        d6m_label=_fmt(a6,  "{:.2f}"), d6m_color=_caccel(a6,  yoy),
        d12m_label=_fmt(yoy, "{:.2f}"), d12m_color=_NEUTRAL,
        col_headers=col_headers,
    )


# ── Transform: NFP (monthly level → MoM change + period averages) ────────────

def _nfp(obs: list) -> Indicator:
    id, name, group = "nfp", "Nonfarm Payrolls (k)", "Labor"
    col_headers = ("3M Avg", "6M Avg", "12M Avg")
    if not obs or len(obs) < 13:
        return _err(id, name, group, col_headers)
    v0  = _v(obs, 0)
    mom = _diff(v0, _v(obs, 1))
    a3  = _diff(v0, _v(obs, 3))
    a3  = a3 / 3  if a3  is not None else None
    a6  = _diff(v0, _v(obs, 6))
    a6  = a6 / 6  if a6  is not None else None
    a12 = _diff(v0, _v(obs, 12))
    a12 = a12 / 12 if a12 is not None else None
    return Indicator(
        id=id, name=name, group=group, as_of=obs[0]["date"],
        value_label=_fmt(mom, "{:+.0f}"),
        d3m_label=_fmt(a3,  "{:+.0f}"), d3m_color=_csign(a3,  1),
        d6m_label=_fmt(a6,  "{:+.0f}"), d6m_color=_csign(a6,  1),
        d12m_label=_fmt(a12, "{:+.0f}"), d12m_color=_csign(a12, 1),
        col_headers=col_headers,
    )


# ── Transform: unemployment rate (level + pp changes) ────────────────────────

def _unemployment(obs: list) -> Indicator:
    id, name, group = "unrate", "Unemployment Rate (%, Δpp)", "Labor"
    if not obs:
        return _err(id, name, group)
    v0  = _v(obs, 0)
    d3  = _diff(v0, _at(obs, 91))
    d6  = _diff(v0, _at(obs, 182))
    d12 = _diff(v0, _at(obs, 365))
    return Indicator(
        id=id, name=name, group=group, as_of=obs[0]["date"],
        value_label=_fmt(v0, "{:.1f}"),
        d3m_label=_fmt(d3,  "{:+.1f}"), d3m_color=_csign(d3,  -1),
        d6m_label=_fmt(d6,  "{:+.1f}"), d6m_color=_csign(d6,  -1),
        d12m_label=_fmt(d12, "{:+.1f}"), d12m_color=_csign(d12, -1),
    )


# ── Transform: activity index → YoY% + change in YoY rate ───────────────────

def _activity_yoy(obs: list, id: str, name: str, group: str,
                   pos_good: int = 1) -> Indicator:
    col_headers = ("Δ vs 3M", "Δ vs 6M", "Δ vs 12M")
    if not obs or len(obs) < 13:
        return _err(id, name, group, col_headers)
    v0,  v3,  v6,  v12 = _v(obs,0),  _v(obs,3),  _v(obs,6),  _v(obs,12)
    v15, v18, v24      = _v(obs,15), _v(obs,18), _v(obs,24)
    yoy0  = _ann(v0,  v12, 12, 12)
    yoy3  = _ann(v3,  v15, 12, 12)
    yoy6  = _ann(v6,  v18, 12, 12)
    yoy12 = _ann(v12, v24, 12, 12)
    d3  = _diff(yoy0, yoy3)
    d6  = _diff(yoy0, yoy6)
    d12 = _diff(yoy0, yoy12)
    return Indicator(
        id=id, name=name, group=group, as_of=obs[0]["date"],
        value_label=_fmt(yoy0, "{:.1f}"),
        d3m_label=_fmt(d3,  "{:+.1f}"), d3m_color=_csign(d3,  pos_good),
        d6m_label=_fmt(d6,  "{:+.1f}"), d6m_color=_csign(d6,  pos_good),
        d12m_label=_fmt(d12, "{:+.1f}"), d12m_color=_csign(d12, pos_good),
        col_headers=col_headers,
    )


# ── Transform: job openings / unemployed workers ratio ───────────────────────

def _jo_u_ratio(obs_j: list, obs_u: list) -> Indicator:
    id, name, group = "jo_u", "Job Openings / Unemployed Workers (×)", "Labor"
    if not obs_j or not obs_u:
        return _err(id, name, group)
    v0j, v0u = _v(obs_j, 0), _v(obs_u, 0)
    if v0j is None or not v0u:
        return _err(id, name, group)
    r0 = v0j / v0u

    def rat(days):
        rj, ru = _at(obs_j, days), _at(obs_u, days)
        return rj / ru if rj is not None and ru else None

    r3, r6, r12 = rat(91), rat(182), rat(365)
    d3  = _diff(r0, r3)
    d6  = _diff(r0, r6)
    d12 = _diff(r0, r12)
    return Indicator(
        id=id, name=name, group=group, as_of=obs_j[0]["date"],
        value_label=_fmt(r0, "{:.2f}"),
        d3m_label=_fmt(d3,  "{:+.2f}"), d3m_color=_csign(d3,  1),
        d6m_label=_fmt(d6,  "{:+.2f}"), d6m_color=_csign(d6,  1),
        d12m_label=_fmt(d12, "{:+.2f}"), d12m_color=_csign(d12, 1),
    )


# ── Transform: real GDP (already QoQ SAAR%, quarterly) ───────────────────────

def _gdp(obs: list) -> Indicator:
    id, name, group = "gdp", "Real GDP (QoQ SAAR %)", "Activity"
    col_headers = ("1Q Ago", "2Q Ago", "4Q Ago")
    if not obs or len(obs) < 5:
        return _err(id, name, group, col_headers)
    v0, v1, v2, v4 = _v(obs,0), _v(obs,1), _v(obs,2), _v(obs,4)
    return Indicator(
        id=id, name=name, group=group, as_of=obs[0]["date"],
        value_label=_fmt(v0, "{:.1f}"),
        d3m_label=_fmt(v1,  "{:.1f}"), d3m_color=_csign(v1,  1),
        d6m_label=_fmt(v2,  "{:.1f}"), d6m_color=_csign(v2,  1),
        d12m_label=_fmt(v4, "{:.1f}"), d12m_color=_csign(v4,  1),
        col_headers=col_headers,
    )


# ── Transform: level with absolute changes ───────────────────────────────────

def _level_abs(obs: list, id: str, name: str, group: str,
               value_fmt: str, chg_fmt: str, pos_good: int = 0) -> Indicator:
    if not obs:
        return _err(id, name, group)
    v0  = _v(obs, 0)
    d3  = _diff(v0, _at(obs, 91))
    d6  = _diff(v0, _at(obs, 182))
    d12 = _diff(v0, _at(obs, 365))
    return Indicator(
        id=id, name=name, group=group, as_of=obs[0]["date"],
        value_label=_fmt(v0, value_fmt),
        d3m_label=_fmt(d3,  chg_fmt), d3m_color=_csign(d3,  pos_good),
        d6m_label=_fmt(d6,  chg_fmt), d6m_color=_csign(d6,  pos_good),
        d12m_label=_fmt(d12, chg_fmt), d12m_color=_csign(d12, pos_good),
    )


# ── ETF indicators (yfinance history + Finnhub real-time quote) ──────────────

_ETF_SYMBOLS = {
    "GLD": ("Gold — GLD ETF ($)",                    "FX & Commodities"),
    "IWM": ("Small Caps — IWM ($)",                  "Equities"),
    "EEM": ("Emerging Markets — EEM ($)",          "Equities"),
    "EFA": ("Intl Developed — EFA ($)",            "Equities"),
    # Select Sector SPDRs (11), alphabetical by sector name
    "XLC": ("Communication Services — XLC ($)",      "Equities"),
    "XLY": ("Consumer Discretionary — XLY ($)",    "Equities"),
    "XLP": ("Consumer Staples — XLP ($)",           "Equities"),
    "XLE": ("Energy — XLE ($)",                    "Equities"),
    "XLF": ("Financials — XLF ($)",                "Equities"),
    "XLV": ("Health Care — XLV ($)",               "Equities"),
    "XLI": ("Industrials — XLI ($)",               "Equities"),
    "XLB": ("Materials — XLB ($)",                  "Equities"),
    "XLK": ("Technology — XLK ($)",               "Equities"),
    "XLU": ("Utilities — XLU ($)",                 "Equities"),
    "XLRE": ("Real Estate — XLRE ($)",              "Equities"),
}

_ETF_COL_HEADERS = ("3M %", "6M %", "12M %")


def _fetch_etf_indicators() -> list:
    """Fetch all ETF indicators using yfinance for history and Finnhub for current price.

    Returns a list of Indicators ordered by _ETF_SYMBOLS insertion order.
    3M/6M/12M columns show price % change over those horizons.
    """
    import yfinance as yf

    symbols = list(_ETF_SYMBOLS.keys())
    results = []

    # ── Finnhub real-time quotes (current price + as-of date) ────────────────
    fh_quotes: dict[str, dict] = {}
    if FINNHUB_API_KEY:
        for sym in symbols:
            try:
                r = requests.get(
                    f"{FINNHUB_BASE}/quote",
                    params={"symbol": sym},
                    headers={"X-Finnhub-Token": FINNHUB_API_KEY},
                    timeout=10,
                )
                r.raise_for_status()
                fh_quotes[sym] = r.json()
            except Exception as exc:
                logger.warning("Finnhub quote failed [%s]: %s", sym, exc)

    # ── yfinance historical closes for % change calculations ─────────────────
    hist: dict[str, list] = {}   # symbol → sorted list of (date_str, close)
    try:
        raw = yf.download(symbols, period="13mo", auto_adjust=True, progress=False)["Close"]
        raw = raw.dropna(how="all")
        for sym in symbols:
            if sym in raw.columns:
                series = raw[sym].dropna()
                hist[sym] = [
                    (d.strftime("%Y-%m-%d"), float(v))
                    for d, v in zip(series.index, series.values)
                ]
    except Exception as exc:
        logger.warning("yfinance bulk download failed: %s", exc)

    # ── Build one Indicator per ETF ───────────────────────────────────────────
    def _pct(v_new, v_old):
        if v_old and v_old != 0:
            return (v_new / v_old - 1) * 100
        return None

    def _color(v):
        if v is None or v == 0:
            return _NEUTRAL
        return _GREEN if v > 0 else _RED

    for sym, (name, group) in _ETF_SYMBOLS.items():
        id_ = sym.lower()
        col_headers = _ETF_COL_HEADERS

        prices = hist.get(sym, [])
        q      = fh_quotes.get(sym, {})
        current = q.get("c") or (prices[-1][1] if prices else None)
        ts      = q.get("t")
        as_of   = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else (prices[-1][0] if prices else "—")

        if not current or not prices:
            results.append(_err(id_, name, group, col_headers))
            continue

        # Find closes ~63 / 126 / 252 trading days ago
        def _close_n_days_ago(n: int) -> float | None:
            idx = max(0, len(prices) - 1 - n)
            return prices[idx][1] if prices else None

        p3m  = _close_n_days_ago(63)
        p6m  = _close_n_days_ago(126)
        p12m = _close_n_days_ago(252)

        d3  = _pct(current, p3m)
        d6  = _pct(current, p6m)
        d12 = _pct(current, p12m)

        chart = [{"date": d, "value": round(v, 4)} for d, v in prices]

        results.append(Indicator(
            id=id_, name=name, group=group,
            as_of=as_of,
            col_headers=col_headers,
            value_label=f"${current:,.2f}",
            d3m_label=(_fmt(d3, "{:+.1f}") + "%") if d3 is not None else "—",
            d3m_color=_color(d3),
            d6m_label=(_fmt(d6, "{:+.1f}") + "%") if d6 is not None else "—",
            d6m_color=_color(d6),
            d12m_label=(_fmt(d12, "{:+.1f}") + "%") if d12 is not None else "—",
            d12m_color=_color(d12),
            chart_series=chart,
            chart_label="$/share",
        ))

    return results


# ── Master fetch ──────────────────────────────────────────────────────────────

def fetch_all_indicators() -> tuple[list, str]:
    """Fetch all FRED indicators. Returns (indicators, timestamp_str)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    if not FRED_API_KEY:
        return [], "FRED_API_KEY not set"

    indicators = []

    # ── Labor ─────────────────────────────────────────────────────────────────
    payems_obs   = _fetch("PAYEMS", 120)             # NFP level, monthly
    unrate_obs   = _fetch("UNRATE", 120)             # Unemployment rate, monthly
    civpart_obs  = _fetch("CIVPART", 120)            # Labor force participation rate, monthly
    jtsjol_obs   = _fetch("JTSJOL", 120)             # Job openings (k), monthly
    unemploy_obs = _fetch("UNEMPLOY", 120)           # Unemployed (k), monthly
    icsa_obs     = _fetch("ICSA", 400)               # Initial jobless claims, weekly

    ind = _nfp(payems_obs)
    ind.chart_series = _chart_mom(payems_obs)
    ind.chart_label = "MoM Δ (k)"
    indicators.append(ind)

    ind = _unemployment(unrate_obs)
    ind.chart_series = _chart_raw(unrate_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _level_abs(civpart_obs, "civpart", "Labor Force Participation (%, Δpp)", "Labor",
                     "{:.1f}", "{:+.1f}", 1)
    ind.chart_series = _chart_raw(civpart_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _jo_u_ratio(jtsjol_obs, unemploy_obs)
    ind.chart_series = _chart_ratio(jtsjol_obs, unemploy_obs)
    ind.chart_label = "ratio (×)"
    indicators.append(ind)

    ind = _level_abs(icsa_obs, "icsa", "Initial Jobless Claims (Δ)", "Labor",
                     "{:,.0f}", "{:+,.0f}", -1)
    ind.chart_series = _chart_raw(icsa_obs)
    ind.chart_label = "claims"
    indicators.append(ind)

    # ── Activity ──────────────────────────────────────────────────────────────
    gdp_obs    = _fetch("A191RL1Q225SBEA", 40)    # Real GDP QoQ SAAR%, quarterly
    indpro_obs = _fetch("INDPRO", 120)             # Industrial production index, monthly
    pcec96_obs = _fetch("PCEC96", 120)             # Real PCE, monthly
    ind = _gdp(gdp_obs)
    ind.chart_series = _chart_raw(gdp_obs)
    ind.chart_label = "QoQ SAAR %"
    indicators.append(ind)

    ind = _activity_yoy(indpro_obs, "indpro", "Industrial Production (YoY %, Δpp)", "Activity", 1)
    ind.chart_series = _chart_yoy(indpro_obs)
    ind.chart_label = "YoY %"
    indicators.append(ind)

    ind = _activity_yoy(pcec96_obs, "pcec96", "Real Consumer Spending (YoY %, Δpp)", "Activity", 1)
    ind.chart_series = _chart_yoy(pcec96_obs)
    ind.chart_label = "YoY %"
    indicators.append(ind)

    # ── Inflation ─────────────────────────────────────────────────────────────
    hcpi_obs    = _fetch("CPIAUCSL", 120)       # Headline CPI index, monthly
    cpi_obs     = _fetch("CPILFESL", 120)       # Core CPI index, monthly
    pce_obs     = _fetch("PCEPILFE", 120)       # Core PCE index, monthly
    ahe_obs     = _fetch("CES0500000003", 120)  # Avg hourly earnings, monthly
    shelter_obs = _fetch("CUSR0000SAH1", 120)   # CPI shelter index, monthly
    be_obs      = _fetch("T5YIFR", 400)         # 5Y5Y breakeven, daily

    ind = _infl_ann(hcpi_obs, "headline_cpi", "Headline CPI (%)", "Inflation")
    ind.chart_series = _chart_yoy(hcpi_obs)
    ind.chart_label = "YoY %"
    indicators.append(ind)

    ind = _infl_ann(cpi_obs, "core_cpi", "Core CPI (%)", "Inflation")
    ind.chart_series = _chart_yoy(cpi_obs)
    ind.chart_label = "YoY %"
    indicators.append(ind)

    ind = _infl_ann(pce_obs, "core_pce", "Core PCE (%)", "Inflation")
    ind.chart_series = _chart_yoy(pce_obs)
    ind.chart_label = "YoY %"
    indicators.append(ind)

    ind = _infl_ann(ahe_obs, "ahe", "Avg Hourly Earnings (%)", "Inflation")
    ind.chart_series = _chart_yoy(ahe_obs)
    ind.chart_label = "YoY %"
    indicators.append(ind)

    ind = _infl_ann(shelter_obs, "shelter_cpi", "Shelter CPI (%)", "Inflation")
    ind.chart_series = _chart_yoy(shelter_obs)
    ind.chart_label = "YoY %"
    indicators.append(ind)

    ind = _rate_bps(be_obs, "t5yifr", "5Y5Y Breakeven (%, Δbp)", "Inflation", -1)
    ind.chart_series = _chart_raw(be_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    # ── Rates & Curve ─────────────────────────────────────────────────────────
    dff_obs    = _fetch("DFF",    400)
    dgs2_obs   = _fetch("DGS2",   400)
    dgs10_obs  = _fetch("DGS10",  400)
    dgs30_obs  = _fetch("DGS30",  400)
    t10y2y_obs = _fetch("T10Y2Y", 400)
    dfii10_obs = _fetch("DFII10", 400)

    ind = _rate_bps(dff_obs, "dff", "Fed Funds Rate (%, Δbp)", "Rates & Curve", 0)
    ind.chart_series = _chart_raw(dff_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _rate_bps(dgs2_obs, "dgs2", "2Y Treasury (%, Δbp)", "Rates & Curve", 0)
    ind.chart_series = _chart_raw(dgs2_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _rate_bps(dgs10_obs, "dgs10", "10Y Treasury (%, Δbp)", "Rates & Curve", 0)
    ind.chart_series = _chart_raw(dgs10_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _rate_bps(dgs30_obs, "dgs30", "30Y Treasury (%, Δbp)", "Rates & Curve", 0)
    ind.chart_series = _chart_raw(dgs30_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _rate_bps(t10y2y_obs, "t10y2y", "10Y–2Y Spread (%, Δbp)", "Rates & Curve", 0)
    ind.chart_series = _chart_raw(t10y2y_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _spread_bps(dgs30_obs, dgs10_obs, "t30y10y", "30Y–10Y Spread (bp, Δbp)", "Rates & Curve", 0)
    ind.chart_series = _chart_spread(dgs30_obs, dgs10_obs)
    ind.chart_label = "bps"
    indicators.append(ind)

    ind = _rate_bps(dfii10_obs, "dfii10", "10Y Real Yield (%, Δbp)", "Rates & Curve", 0)
    ind.chart_series = _chart_raw(dfii10_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    # ── Credit ────────────────────────────────────────────────────────────────
    hy_obs      = _fetch("BAMLH0A0HYM2", 400)   # HY OAS, daily, in %
    ig_obs      = _fetch("BAMLC0A0CM",   400)   # IG OAS, daily, in %
    lending_obs = _fetch("DRTSCILM",      40)   # Bank lending standards, quarterly
    nfci_obs    = _fetch("NFCI",         400)   # Chicago Fed National Financial Conditions Index, weekly

    ind = _rate_bps(hy_obs, "hy_oas", "HY OAS (%, Δbp)", "Credit", -1)
    ind.chart_series = _chart_raw(hy_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _rate_bps(ig_obs, "ig_oas", "IG OAS (%, Δbp)", "Credit", -1)
    ind.chart_series = _chart_raw(ig_obs)
    ind.chart_label = "%"
    indicators.append(ind)

    ind = _level_abs(lending_obs, "lending", "Bank Lending Standards (%, Δpp)", "Credit",
                     "{:.1f}", "{:+.1f}", -1)
    ind.chart_series = _chart_raw(lending_obs)
    ind.chart_label = "net % tightening"
    indicators.append(ind)

    ind = _level_abs(nfci_obs, "nfci", "National Financial Conditions Index (Δ)", "Credit",
                     "{:.2f}", "{:+.2f}", -1)
    ind.chart_series = _chart_raw(nfci_obs)
    ind.chart_label = "index"
    indicators.append(ind)

    # ── Risk & Markets ────────────────────────────────────────────────────────
    sp500_obs = _fetch("SP500",   400)
    vix_obs   = _fetch("VIXCLS",  400)
    sent_obs  = _fetch("UMCSENT", 120)   # U of Mich Consumer Sentiment, monthly

    ind = _pct_chg(sp500_obs, "sp500", "S&P 500 (Δ%)", "Risk & Markets", 1, "{:,.0f}")
    ind.chart_series = _chart_raw(sp500_obs)
    ind.chart_label = "price"
    indicators.append(ind)

    ind = _level_abs(vix_obs, "vix", "VIX (Δ pts)", "Risk & Markets", "{:.1f}", "{:+.1f}", -1)
    ind.chart_series = _chart_raw(vix_obs)
    ind.chart_label = "pts"
    indicators.append(ind)

    ind = _level_abs(sent_obs, "umcsent", "Consumer Sentiment (Δ pts)", "Risk & Markets", "{:.1f}", "{:+.1f}", 1)
    ind.chart_series = _chart_raw(sent_obs)
    ind.chart_label = "index"
    indicators.append(ind)

    # ── Equities + Gold ETF (yfinance history, Finnhub real-time price) ─────────
    indicators.extend(_fetch_etf_indicators())

    # ── FX & Commodities ──────────────────────────────────────────────────────
    eurusd_obs = _fetch("DEXUSEU",    400)
    usdcny_obs = _fetch("DEXCHUS",    400)
    usdjpy_obs = _fetch("DEXJPUS",    400)
    dxy_obs    = _fetch("DTWEXBGS",   300)   # weekly broad dollar index
    wti_obs    = _fetch("DCOILWTICO", 400)

    ind = _pct_chg(eurusd_obs, "eurusd", "EUR/USD (Δ%)", "FX & Commodities", 0, "{:.4f}")
    ind.chart_series = _chart_raw(eurusd_obs)
    ind.chart_label = "rate"
    indicators.append(ind)

    ind = _pct_chg(usdcny_obs, "usdcny", "USD/CNY (Δ%)", "FX & Commodities", 0, "{:.4f}")
    ind.chart_series = _chart_raw(usdcny_obs)
    ind.chart_label = "rate"
    indicators.append(ind)

    ind = _pct_chg(usdjpy_obs, "usdjpy", "USD/JPY (Δ%)", "FX & Commodities", 0, "{:.2f}")
    ind.chart_series = _chart_raw(usdjpy_obs)
    ind.chart_label = "JPY per USD"
    indicators.append(ind)

    ind = _pct_chg(dxy_obs, "dxy", "Broad Dollar Index (Δ%)", "FX & Commodities", 0, "{:.2f}")
    ind.chart_series = _chart_raw(dxy_obs)
    ind.chart_label = "index"
    indicators.append(ind)

    ind = _pct_chg(wti_obs, "wti", "WTI Crude ($, Δ%)", "FX & Commodities", 0, "${:.2f}")
    ind.chart_series = _chart_raw(wti_obs)
    ind.chart_label = "$/barrel"
    indicators.append(ind)

    return indicators, timestamp
