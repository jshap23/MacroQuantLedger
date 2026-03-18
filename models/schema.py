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


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    status: str = ""
    next_step: str = ""
    priority: str = "—"
    last_touched: Optional[datetime] = None


class Skill(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    level: str = "—"
    building: str = ""
    interview_relevance: str = "—"
    last_touched: Optional[datetime] = None


class ReadinessItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    area: str = ""
    strength: str = ""
    evidence: str = ""
    action: str = ""
    last_touched: Optional[datetime] = None


class QuantTracker(BaseModel):
    projects: list[Project] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    readiness: list[ReadinessItem] = Field(default_factory=list)


class Reconciliation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: datetime = Field(default_factory=datetime.now)
    macro_scan: str = ""
    quant_check: str = ""
    time_macro: int = 33
    time_quant: int = 33
    time_other: int = 34
    synthesis: str = ""


class AppState(BaseModel):
    macro_views: list[MacroView] = Field(default_factory=list)
    macro_notes: str = ""
    quant_tracker: QuantTracker = Field(default_factory=QuantTracker)
    reconciliations: list[Reconciliation] = Field(default_factory=list)


DEFAULT_MACRO_VIEWS = [
    MacroView(id="growth", name="Growth Trajectory"),
    MacroView(id="global_growth", name="Global Growth"),
    MacroView(id="inflation", name="Inflation Dynamics"),
    MacroView(id="fed", name="Fed Policy Path"),
    MacroView(id="term_premium", name="Term Premium"),
    MacroView(id="usd", name="USD"),
    MacroView(id="credit", name="Credit"),
]


def default_state() -> AppState:
    return AppState(
        macro_views=[v.model_copy() for v in DEFAULT_MACRO_VIEWS],
        macro_notes="",
        quant_tracker=QuantTracker(
            projects=[Project()],
            skills=[Skill()],
            readiness=[ReadinessItem()],
        ),
        reconciliations=[],
    )
