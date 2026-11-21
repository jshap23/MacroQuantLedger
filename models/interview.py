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
    # One concrete thing to do differently next time. Plain str, not Literal, so
    # legacy answers that never recorded one load as "".
    fix: str = ""
    # "ok" when score, critique, and fix were all present; "partial" when a score
    # was saved without critique or fix. "" marks a legacy answer from before
    # status was recorded.
    evaluation_status: str = ""
    is_retry: bool = False
    # True when the answer was dictated and submitted as a raw speech-to-text
    # transcript rather than typed. Used to scope the grader's transcription
    # safety net and to keep voice-vs-typed grading auditable.
    voice: bool = False
    # Phase 2 provenance: "voice" or "typed" as recorded at submit time. Plain
    # str, not Literal, so legacy answers load as "" and derive from ``voice``.
    # Phase 3 adds "mixed" without a schema change.
    input_method: str = ""


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
    # "ok" when overall text plus at least one item in each list is present;
    # "partial" when some but not all; "missing" when nothing usable came back.
    # "" marks a legacy postmortem that never recorded a status. "pending" marks
    # a completed session whose summary is written separately by
    # synthesize_session().
    status: str = ""
    # When status is "missing", which failure produced it: "provider" for a
    # transport/auth failure, "output" when the model's content was unusable.
    synthesis_error: str = ""


class FactCheckClaim(BaseModel):
    claim: str
    # "answer" for something the candidate said, "card" for a dated fact on the stored View.
    origin: str = "answer"
    # "current", "outdated", "wrong" or "unverifiable". Plain str, not Literal, so an
    # unexpected value in a saved file can never make the history unreadable.
    status: str = "unverifiable"
    latest_value: str = ""
    reference_period: str = ""
    released: str = ""
    source_url: str = ""
    source_title: str = ""
    note: str = ""


class FactCheck(BaseModel):
    # "ok" when the model returned a usable list (possibly empty); "missing" on failure.
    status: str = "missing"
    # "", "provider", "output", or "no_citations" (an ok result with no cited sources).
    error: str = ""
    checked_at: datetime = Field(default_factory=_now)
    model: str = ""
    claims: list[FactCheckClaim] = Field(default_factory=list)


class InterviewSession(BaseModel):
    id: str = Field(default_factory=_uuid)
    started_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None
    mode: InterviewMode
    preset_key: str = ""
    prompt_pack_version: str = ""
    # Which rubric graded this session: "argument-v3"/"technical-v3"/
    # "interview-v3", or "custom" for a prompt-override session. Plain str, not
    # Literal, so legacy sessions load as "" and derive their effective id.
    rubric_id: str = ""
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
    surprise: bool = False
    pending_move: dict = Field(default_factory=dict)
    status: Literal["active", "completed", "abandoned"] = "active"
    questions: list[InterviewQuestion] = Field(default_factory=list)
    postmortem: Optional[InterviewPostmortem] = None
    # Cached on demand from the postmortem "Show a strong version" button so a
    # re-render never re-bills the extra LLM call.
    reference_answer: str = ""
    # Advisory web-grounded check of the answer's facts. Never scored; None until the
    # user clicks Check facts.
    fact_check: Optional[FactCheck] = None


class InterviewDatabase(BaseModel):
    preferred_model: str = ""
    sessions: list[InterviewSession] = Field(default_factory=list)
