"""Pure synthesis functions — no IO, no UI."""
from __future__ import annotations
from models.schema import MacroView, AssetView

# Maps macro view id → relevant FRED indicator ids
MACRO_FRED_MAP: dict[str, list[str]] = {
    "growth":        ["gdp", "indpro", "rsxfs", "icsa"],
    "global_growth": ["efa", "eem", "wti"],
    "inflation":     ["core_cpi", "core_pce", "ahe", "t5yifr"],
    "fed":           ["dff", "dgs2", "t10y2y"],
    "term_premium":  ["dgs10", "dfii10", "t30y10y"],
    "credit":        ["hy_oas", "ig_oas", "nfci"],
    "usd":           ["dxy", "eurusd", "usdjpy"],
}

# Short display names for indicator ids in the FRED data line
_IND_SHORT: dict[str, str] = {
    "gdp":         "GDP QoQ",
    "indpro":      "IP",
    "rsxfs":       "Retail Ctrl",
    "icsa":        "Claims",
    "efa":         "Intl Dev",
    "eem":         "EM",
    "wti":         "WTI",
    "core_cpi":    "Core CPI",
    "core_pce":    "Core PCE",
    "ahe":         "AHE",
    "t5yifr":      "5Y5Y B/E",
    "shelter_cpi": "Shelter",
    "dff":         "Fed Funds",
    "dgs2":        "2Y",
    "t10y2y":      "10Y–2Y",
    "dgs10":       "10Y",
    "dfii10":      "10Y Real",
    "t30y10y":     "30Y–10Y",
    "hy_oas":      "HY OAS",
    "ig_oas":      "IG OAS",
    "nfci":        "NFCI",
    "dxy":         "DXY",
    "eurusd":      "EUR/USD",
    "usdjpy":      "USD/JPY",
}

VERBAL_SCORE: dict[str, str] = {
    "5": "strong overweight",
    "4": "overweight",
    "3": "neutral",
    "2": "underweight",
    "1": "strong underweight",
    "—": "no view",
}


def macro_prose(view: MacroView) -> str:
    """Compose a spoken-style paragraph from a MacroView's qualitative fields."""
    parts: list[str] = []

    conviction = view.conviction if view.conviction not in ("—", "") else None
    if conviction:
        parts.append(f"On {view.name}: I'm {view.direction.lower()}, {conviction.lower()} conviction.")
    else:
        parts.append(f"On {view.name}: I'm {view.direction.lower()}.")

    if view.lean and view.lean.strip():
        lean = view.lean.strip()
        if not lean.endswith((".", "?", "!")):
            lean += "."
        parts.append(lean)

    signals = [s.strip() for s in view.signals if s.strip()]
    if len(signals) == 1:
        parts.append(f"The key thing I'd point to: {signals[0]}.")
    elif len(signals) == 2:
        parts.append(f"Two things I'd cite: {signals[0]}; {signals[1]}.")
    elif len(signals) >= 3:
        parts.append(f"Three things I'd point to: {'; '.join(signals[:3])}.")

    if view.counter and view.counter.strip():
        counter = view.counter.strip()
        lower_start = counter[0].lower() + counter[1:] if len(counter) > 1 else counter.lower()
        parts.append(f"I'd change my mind if {lower_start}")
        if not parts[-1].endswith((".", "?", "!")):
            parts[-1] += "."

    return " ".join(parts)


def fred_snippet(ind_id: str, fred_index: dict) -> str | None:
    """Return a compact data string for one indicator, e.g. 'Core CPI: 3.1% (-0.2% 3M)'."""
    ind = fred_index.get(ind_id)
    if ind is None or ind.error or not ind.value_label or ind.value_label == "—":
        return None
    short = _IND_SHORT.get(ind_id, ind_id)
    delta = ""
    if ind.d3m_label and ind.d3m_label not in ("—", ""):
        delta = f" ({ind.d3m_label} 3M)"
    elif ind.d12m_label and ind.d12m_label not in ("—", ""):
        delta = f" ({ind.d12m_label} 12M)"
    return f"{short}: {ind.value_label}{delta}"


def asset_verbal(av: AssetView, tenure_entry: dict | None) -> dict:
    """Return a verbal summary dict for one AssetView."""
    verbal = VERBAL_SCORE.get(av.direction, "no view")
    held_str = ""
    if tenure_entry:
        days = tenure_entry.get("days_held")
        unknown = tenure_entry.get("unknown_start", True)
        if days is not None:
            prefix = ">" if unknown else ""
            held_str = f"{prefix}{days}d"
    return {
        "id": av.id,
        "name": av.name,
        "score": av.direction,
        "verbal": verbal,
        "note": av.note.strip() if av.note else "",
        "held": held_str,
    }
