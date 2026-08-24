from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional
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


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ViewFact(BaseModel):
    """One concise piece of evidence supporting a point."""
    id: str = Field(default_factory=_uuid)
    text: str = ""
    source: str = ""
    as_of: str = ""
    note: str = ""


class ViewPoint(BaseModel):
    """An ordered pillar in a user's spoken view."""
    id: str = Field(default_factory=_uuid)
    title: str = ""
    facts: list[ViewFact] = Field(default_factory=list)


class ViewPracticeMeta(BaseModel):
    last_practiced: Optional[datetime] = None
    practice_count: int = 0
    delivery_attempts: int = 0
    discussion_attempts: int = 0
    defense_attempts: int = 0
    latest_diagnostic: list[str] = Field(default_factory=list)


class TopicView(BaseModel):
    """Structured mental framework; deliberately not an opaque note blob."""
    id: str = Field(default_factory=_uuid)
    name: str = "Untitled View"
    bottom_line: str = ""
    points: list[ViewPoint] = Field(
        default_factory=lambda: [ViewPoint(), ViewPoint(), ViewPoint()]
    )
    counterargument: str = ""
    changes_my_mind: str = ""
    watch: list[str] = Field(default_factory=list)
    status: Literal["Developing", "Ready", "Needs Refresh"] = "Developing"
    priority: Literal["Core", "Normal", "Low Priority"] = "Normal"
    archived: bool = False
    related_view_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
    practice: ViewPracticeMeta = Field(default_factory=ViewPracticeMeta)


class AppState(BaseModel):
    macro_views: list[MacroView] = Field(default_factory=list)
    macro_notes: str = ""
    asset_views: list[AssetView] = Field(default_factory=list)
    quant_focus: str = ""
    quant_focus_next: str = ""
    reconciliations: list[Reconciliation] = Field(default_factory=list)
    briefing: BriefingStrip = Field(default_factory=BriefingStrip)
    trades: list[Trade] = Field(default_factory=list)
    topic_views: list[TopicView] = Field(default_factory=list)
    topic_views_version: int = 0


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
        topic_views_version=3,
    )
