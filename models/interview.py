from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional
import uuid

from pydantic import BaseModel, Field


InterviewMode = Literal["Discussion", "Drill", "Simulation", "Research Defense"]


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InterviewAnswer(BaseModel):
    text: str
    submitted_at: datetime = Field(default_factory=_now)
    score: Optional[int] = None
    failure_tags: list[str] = Field(default_factory=list)
    critique: str = ""
    is_retry: bool = False


class InterviewQuestion(BaseModel):
    id: str = Field(default_factory=_uuid)
    text: str
    topic: str = ""
    concept: str = ""
    difficulty: Optional[str] = None
    answers: list[InterviewAnswer] = Field(default_factory=list)
    should_return: bool = False
    next_review_date: Optional[date] = None
    review_priority: int = 0
    successful_retries: int = 0


class InterviewPostmortem(BaseModel):
    overall_performance: str = ""
    biggest_problems: list[str] = Field(default_factory=list)
    strongest_areas: list[str] = Field(default_factory=list)
    concepts_to_repeat: list[str] = Field(default_factory=list)
    root_causes: dict[str, str] = Field(default_factory=dict)
    trend: str = ""


class InterviewSession(BaseModel):
    id: str = Field(default_factory=_uuid)
    started_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None
    mode: InterviewMode
    preset_key: str = ""
    prompt_pack_version: str = ""
    prompt_override: str = ""
    topic: str
    role: str = ""
    focus_areas: str = ""
    materials: str = ""
    view_ids: list[str] = Field(default_factory=list)
    practice_style: str = ""
    view_context: str = ""
    model_note_ids: list[str] = Field(default_factory=list)
    model_note_titles: list[str] = Field(default_factory=list)
    model_context: str = ""
    target_questions: int = 10
    weakness_session: bool = False
    model: str = ""
    compact_brief: str = ""
    pending_move: dict = Field(default_factory=dict)
    status: Literal["active", "completed", "abandoned"] = "active"
    questions: list[InterviewQuestion] = Field(default_factory=list)
    postmortem: Optional[InterviewPostmortem] = None


class InterviewDatabase(BaseModel):
    preferred_model: str = ""
    sessions: list[InterviewSession] = Field(default_factory=list)
