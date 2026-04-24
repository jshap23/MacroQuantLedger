from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class MacroView(BaseModel):
    id: str
    name: str
    lean: str = ""
    signals: list[str] = Field(default_factory=lambda: ["", "", ""])
    counter: str = ""
    direction: str = "No View"   # Bullish | Neutral | Bearish | No View
    conviction: str = "—"        # High | Medium | Low | —
    flag: str = "green"
    last_touched: Optional[datetime] = None


class AssetView(BaseModel):
    id: str
    name: str
    group: str                   # "l1" | "equities" | "fixed_income"
    direction: str = "No View"   # Bullish | Neutral | Bearish | No View
    conviction: str = "—"        # High | Medium | Low | —
    note: str = ""
    commentary: str = ""
    last_touched: Optional[datetime] = None


class Reconciliation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: datetime = Field(default_factory=datetime.now)
    macro_scan: str = ""
    quant_check: str = ""
    time_macro: int = 33
    time_quant: int = 33
    time_other: int = 34
    synthesis: str = ""


class BriefingStrip(BaseModel):
    top_of_mind: str = ""
    top_of_mind_touched: Optional[datetime] = None


class Trade(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticker: str
    entry_date: str                  # YYYY-MM-DD
    exit_date: Optional[str] = None  # YYYY-MM-DD; None = open
    size: Optional[float] = None     # $ notional at entry
    note: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class AppState(BaseModel):
    macro_views: list[MacroView] = Field(default_factory=list)
    macro_notes: str = ""
    asset_views: list[AssetView] = Field(default_factory=list)
    quant_focus: str = ""
    quant_focus_next: str = ""
    reconciliations: list[Reconciliation] = Field(default_factory=list)
    briefing: BriefingStrip = Field(default_factory=BriefingStrip)
    trades: list[Trade] = Field(default_factory=list)


DEFAULT_MACRO_VIEWS = [
    MacroView(id="growth", name="US Growth"),
    MacroView(id="global_growth", name="Global Growth"),
    MacroView(id="inflation", name="Inflation"),
    MacroView(id="fed", name="Fed Policy Path"),
    MacroView(id="term_premium", name="Term Premium"),
    MacroView(id="credit", name="Credit"),
    MacroView(id="usd", name="USD"),
]

DEFAULT_ASSET_VIEWS = [
    # Level 1
    AssetView(id="stocks_bonds", name="Stocks vs Bonds", group="l1"),
    # Equities
    AssetView(id="eq_us_lc",  name="US LC",          group="equities"),
    AssetView(id="eq_us_smid",name="US SMID",         group="equities"),
    AssetView(id="eq_europe", name="Europe",          group="equities"),
    AssetView(id="eq_japan",  name="Japan",           group="equities"),
    AssetView(id="eq_em_xch", name="EM x China",      group="equities"),
    AssetView(id="eq_china",  name="China",           group="equities"),
    AssetView(id="eq_pe",     name="Private Equity",  group="equities"),
    # Fixed Income
    AssetView(id="fi_tsy",    name="US Treasuries",   group="fixed_income"),
    AssetView(id="fi_sec",    name="Securitized Credit", group="fixed_income"),
    AssetView(id="fi_lev",    name="Leveraged Credit", group="fixed_income"),
    AssetView(id="fi_global", name="Global Bonds",    group="fixed_income"),
    AssetView(id="fi_em",     name="EM Debt",         group="fixed_income"),
]


def default_state() -> AppState:
    return AppState(
        macro_views=[v.model_copy() for v in DEFAULT_MACRO_VIEWS],
        macro_notes="",
        asset_views=[v.model_copy() for v in DEFAULT_ASSET_VIEWS],
        quant_focus="",
        quant_focus_next="",
        reconciliations=[],
    )
