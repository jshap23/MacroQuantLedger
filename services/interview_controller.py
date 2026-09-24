from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from models.interview import InterviewAnswer, InterviewPostmortem, InterviewQuestion, InterviewSession
from services.interview_llm import (
    CompletionOptions, FAILURE_TAGS, LLMProvider, InterviewOutputError,
    InterviewProviderError, default_provider, interview_model, parse_json_response,
)
from services.interview_prompts import (
    PROMPT_PACK_VERSION, compose_runtime_prompt, get_preset,
)
from storage.interview_store import (
    effective_rubric_id, get_session, load_database, mark_review, save_session,
    weakness_context,
)


# Per-turn token budgets. A first failure is often truncation, so the single
# repair retry gets REPAIR_TOKEN_FACTOR times the first call's budget.
EVAL_MAX_TOKENS = 450
REPAIR_TOKEN_FACTOR = 1.5
QUESTION_RECOVERY_MAX_TOKENS = 100
# The whole-interview review is a separate call after completion, with its own
# budget and its own single repair.
SYNTHESIS_MAX_TOKENS = 900
# Used when the turn's single repair is already spent and the model still did
# not return a next question. Never triggers a third call.
FALLBACK_FOLLOW_UP = (
    "Take that one level deeper: what is the mechanism, and what evidence supports it?"
)


# Anchored scoring rubric, split into three families in Phase 2. Each family
# keeps the same 1-10 score ranges, the same grade-discipline paragraph, and the
# same closing sentence; only the band descriptors differ, so a technical answer
# is not graded against thesis-shaped bands. rubric_id records which family
# graded a session so scores are only compared like with like.
_RUBRIC_INTRO = "integer 1-10, graded against this rubric:\n"

# Argument keeps the Phase 1 band block verbatim so legacy and Phase 1 sessions
# render exactly as before.
_ARGUMENT_BANDS = (
    "  1-2  Did not answer the question asked, or the core claim is wrong.\n"
    "  3-4  Relevant content, but no clear bottom line; factors named without mechanism.\n"
    "  5-6  Clear view stated; partial mechanism; evidence thin, vague, or unsupported.\n"
    "  7-8  Bottom line first; at least one causal chain explained end to end; evidence\n"
    "       with magnitudes; states what would falsify the view.\n"
    "  9-10 All of 7-8, plus handles the strongest counterargument and translates the\n"
    "       view into an implementable decision.\n"
)

_TECHNICAL_BANDS = (
    "  1-2  Did not answer the question asked, or the result or method is wrong.\n"
    "  3-4  Relevant approach, but the result is wrong or unfinished, or steps are\n"
    "       missing so the reasoning can't be followed.\n"
    "  5-6  Correct result or method, with gaps: key steps skipped, assumptions\n"
    "       unstated, or imprecise terms.\n"
    "  7-8  Correct result or method; reasoning shown in clear steps; assumptions\n"
    "       stated; precise terms.\n"
    "  9-10 All of 7-8, plus a sanity check or edge case, and says when the method\n"
    "       breaks down or what a better alternative would be.\n"
)

_INTERVIEW_BANDS = (
    "  1-2  Did not answer the question asked, or the answer hurts the candidacy.\n"
    "  3-4  Relevant but generic: no specific example, or the candidate's own role\n"
    "       is unclear.\n"
    "  5-6  Answers the question with a specific example, but the result is vague\n"
    "       or the answer rambles.\n"
    "  7-8  Direct answer first; a specific example with the candidate's own\n"
    "       actions; a concrete result, quantified where possible; concise.\n"
    "  9-10 All of 7-8, plus explicit relevance to the role and a reflective point\n"
    "       (what they learned or would do differently).\n"
)

_RUBRIC_BANDS_BY_FAMILY = {
    "argument": _ARGUMENT_BANDS,
    "technical": _TECHNICAL_BANDS,
    "interview": _INTERVIEW_BANDS,
}

# Grade discipline carried over from Phase 1 so the 7-8 bar does not drift.
_RUBRIC_DISCIPLINE = (
    "Grade the answer as given, against the rubric. Do not grade on a curve. Do not\n"
    "withhold 7+ from an answer that meets the 7-8 bar. Most practice answers land\n"
    "3-6; that is expected and is not a reason to compress the scale further."
)

_RUBRIC_CLOSING = (
    "Grade against what this question asks. A narrow follow-up needs a precise "
    "answer to that follow-up, not a full thesis."
)

RUBRICS: dict[str, tuple[str, str]] = {
    family: (
        f"{family}-v3",
        f"{_RUBRIC_INTRO}{bands}{_RUBRIC_DISCIPLINE}\n{_RUBRIC_CLOSING}",
    )
    for family, bands in _RUBRIC_BANDS_BY_FAMILY.items()
}

# These patterns read each family's band block back so the postmortem can print
# a band verbatim and never drift from the rubric text.
_BAND_LINE = re.compile(r"^ {2}(\d+)-(\d+)\s+(.*)$")
_BAND_CONT = re.compile(r"^ {7}(\S.*)$")


def rubric_bands(family: str = "argument") -> list[tuple[str, str]]:
    """The five rubric bands as (label, descriptor), verbatim for a family.

    Descriptors wrapped over two source lines are joined with a single space so
    a band can be shown on one line without rewording anything.
    """
    block = _RUBRIC_BANDS_BY_FAMILY.get(family, _ARGUMENT_BANDS)
    bands: list[tuple[str, str]] = []
    current: list[str] | None = None
    for line in block.splitlines():
        match = _BAND_LINE.match(line)
        if match:
            if current:
                bands.append((current[0], current[1]))
            current = [f"{match.group(1)}-{match.group(2)}", match.group(3).strip()]
            continue
        continuation = _BAND_CONT.match(line)
        if continuation and current:
            current[1] = f"{current[1]} {continuation.group(1).strip()}"
            continue
        if current:
            bands.append((current[0], current[1]))
            current = None
    if current:
        bands.append((current[0], current[1]))
    return bands


def rubric_band_for(
    score: int | None, family: str = "argument",
) -> tuple[str, str, str | None] | None:
    """Map a 1-10 score to (band label, descriptor, next band descriptor).

    ``family`` selects which family's band wording is used. The next-band
    descriptor is None for the top band (9-10), which has no higher band.
    """
    if score is None:
        return None
    bands = rubric_bands(family)
    for index, (label, descriptor) in enumerate(bands):
        low, high = (int(part) for part in label.split("-"))
        if low <= score <= high:
            following = bands[index + 1][1] if index + 1 < len(bands) else None
            return (label, descriptor, following)
    return None


BAND_MIN_COVERAGE = 0.75


def rubric_family_for(session: InterviewSession) -> str:
    """The band family a session's score is shown against.

    A v3 rubric id maps to its family. Every legacy or custom id — "shared-v2",
    "unanchored", "custom" — uses the argument bands, which are the Phase 1
    bands.
    """
    rubric_id = effective_rubric_id(session)
    if rubric_id.endswith("-v3") and rubric_id[:-3] in RUBRICS:
        return rubric_id[:-3]
    return "argument"


def session_band(session: InterviewSession) -> tuple[str, str, str | None] | None:
    """Rubric band for the session's first-attempt average, or None if hidden.

    The band uses the session's own rubric family. Legacy sessions (postmortem
    status "") keep the historical behavior: every graded answer counts and no
    coverage gate applies. New sessions exclude retries and require at least
    BAND_MIN_COVERAGE of first-attempt answers to be scored; a missing
    postmortem shows no band at all.
    """
    postmortem = session.postmortem
    status = postmortem.status if postmortem else ""
    if status == "missing":
        return None
    answers = [answer for question in session.questions for answer in question.answers]
    if status == "":
        scores = [answer.score for answer in answers if answer.score is not None]
    else:
        first_attempts = [answer for answer in answers if not answer.is_retry]
        scores = [answer.score for answer in first_attempts if answer.score is not None]
        if not first_attempts or len(scores) / len(first_attempts) < BAND_MIN_COVERAGE:
            return None
    if not scores:
        return None
    return rubric_band_for(int(sum(scores) / len(scores) + 0.5), rubric_family_for(session))


def band_visible(session: InterviewSession) -> bool:
    """Whether the postmortem band renders for this session.

    Pure and client-free so the gate can be tested directly. Shown for sessions
    graded under a real rubric family (current or the legacy anchored pack);
    hidden for custom-prompt and unanchored sessions, whose scores are not
    comparable.
    """
    return effective_rubric_id(session) not in {"unanchored", "custom"}


def _system(
    session: InterviewSession, current_session_state: str, transcript_note: bool = False,
) -> str:
    return compose_runtime_prompt(
        preset_key=session.preset_key,
        mode=session.mode,
        practice_state=weakness_context(),
        role=session.role,
        focus_areas=session.focus_areas,
        materials="\n\n".join(part for part in (session.materials, session.view_context) if part),
        model_context=session.model_context,
        current_session_state=current_session_state,
        prompt_override=session.prompt_override,
        transcript_note=transcript_note,
    )


def _question_text(data: dict) -> str:
    """Normalize the common question shapes returned by compatible models."""
    value = (
        data.get("question") or data.get("next_question") or data.get("nextQuestion")
        or data.get("text") or ""
    )
    if isinstance(value, dict):
        value = value.get("text") or value.get("question") or value.get("content") or ""
    return str(value).strip()


def _question(data: dict, fallback_topic: str) -> InterviewQuestion:
    """Normalize the common question shapes returned by compatible models."""
    text = _question_text(data)
    if not text:
        raise RuntimeError("The interview model did not return a question.")
    return InterviewQuestion(
        text=text,
        topic=str(data.get("topic") or fallback_topic).strip(),
        concept=str(data.get("concept") or "").strip(),
        difficulty=str(data.get("difficulty") or "").strip() or None,
    )


def _opening_question(session: InterviewSession) -> str:
    """Provide a reliable first turn without relying on JSON-mode support."""
    topic = session.topic
    if session.preset_key == "quant_drill":
        return f"What is the core intuition behind {topic}?"
    if session.preset_key == "job_interview":
        return f"What makes you a strong fit for {session.role or topic}?"
    if session.preset_key == "research_defense":
        return f"What is your main conclusion on {topic}, and what is the strongest evidence for it?"
    if session.preset_key == "model_explain":
        return f"Walk me through {topic}."
    if session.preset_key == "model_defend":
        return f"Why should I believe {topic} is the right tool for a hard problem?"
    if session.preset_key == "model_compare":
        return f"What is the key difference between {topic}, and when would you pick one over the other?"
    if session.preset_key == "model_deep_dive":
        return f"What exactly is {topic} optimizing?"
    return f"What's your view on {topic}?"


def start_session(
    mode: str,
    topic: str,
    role: str = "",
    focus_areas: str = "",
    materials: str = "",
    target_questions: int = 10,
    weakness_session: bool = False,
    model: str = "",
    preset_key: str = "",
    prompt_override: str = "",
    view_ids: list[str] | None = None,
    practice_style: str = "",
    view_context: str = "",
    model_note_ids: list[str] | None = None,
    model_note_titles: list[str] | None = None,
    model_context: str = "",
    initial_question: str = "",
    surprise: bool = False,
    provider: LLMProvider | None = None,
) -> InterviewSession:
    preset = get_preset(preset_key, mode)
    override = prompt_override.strip()
    session = InterviewSession(
        mode=preset.mode,
        preset_key=preset.key,
        prompt_pack_version=PROMPT_PACK_VERSION,
        # A prompt override is graded with the family rubric but marked "custom"
        # so it is excluded from cross-session trends.
        rubric_id="custom" if override else RUBRICS[preset.rubric_family][0],
        prompt_override=override,
        topic=topic.strip() or "General professional interview",
        role=role.strip(),
        focus_areas=focus_areas.strip(),
        materials=materials.strip(),
        view_ids=view_ids or [],
        practice_style=practice_style.strip(),
        view_context=view_context.strip(),
        model_note_ids=model_note_ids or [],
        model_note_titles=model_note_titles or [],
        model_context=model_context or "",
        target_questions=max(1, min(50, int(target_questions))),
        weakness_session=weakness_session or preset.key == "weaknesses",
        model=interview_model(model),
        surprise=surprise,
    )
    # The opening question is deterministic. This makes practice immediately
    # available with providers that do not reliably honor JSON mode (notably
    # some DeepSeek-compatible endpoints), while all later turns still use
    # the selected model to respond to the candidate's actual answer.
    opening = initial_question.strip() or _opening_question(session)
    if opening:
        session.questions.append(_question({"question": opening}, session.topic))
        session.compact_brief = session.materials[:1200] or (model_context or "")[:1200]
        save_session(session)
        return session


def _recent_context(session: InterviewSession) -> list[dict]:
    recent = []
    for question in session.questions[-4:]:
        if question.answers:
            answer = question.answers[-1]
            recent.append({"question": question.text, "answer": answer.text[:1800], "tags": answer.failure_tags})
    return recent


def _compact_critique(value) -> str:
    """Enforce the Drill contract even if a provider ignores prompt limits."""
    text = " ".join(str(value or "").split())
    sentence_ends = [index for index, char in enumerate(text) if char in ".!?" ]
    if len(sentence_ends) >= 2:
        text = text[:sentence_ends[1] + 1]
    words = text.split()
    return " ".join(words[:60])


def _text_value(value) -> str:
    """Flatten a model field that may be a string, number, or list."""
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return "" if value is None else str(value)


def _compact_fix(value) -> str:
    """One concrete fix: a single sentence, trimmed to at most 40 words.

    The sentence cut only fires on punctuation followed by whitespace or the
    end, so decimals like "1.5%" are not mistaken for a sentence break.
    """
    text = " ".join(_text_value(value).split())
    for index, char in enumerate(text):
        if char in ".!?" and (index + 1 == len(text) or text[index + 1].isspace()):
            text = text[:index + 1]
            break
    return " ".join(text.split()[:40])


_SCORE_PATTERN = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(?:/\s*(\d+(?:\.\d+)?))?$")


def _parse_score(value) -> int | None:
    """Accept 7, 7.0, "7", or "7/10"; clamp to 1-10; otherwise None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = _SCORE_PATTERN.match(value.strip())
        if not match:
            return None
        number = float(match.group(1))
        if match.group(2):
            denominator = float(match.group(2))
            if denominator <= 0:
                return None
            number = number / denominator * 10
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return max(1, min(10, int(number + 0.5)))


class TurnEvaluation(BaseModel):
    """One validated turn of private evaluation fields.

    Parsing never raises for a bad field: an unusable field normalizes to its
    empty value so the caller can decide whether to repair the turn or save a
    partial. ``status`` is the storage classification the answer records.
    """

    score: int | None = None
    failure_tags: list[str] = Field(default_factory=list)
    critique: str = ""
    fix: str = ""
    next_question: str = ""
    next_topic: str = ""
    concept: str = ""
    difficulty: str | None = None
    materially_weak: bool = False
    done: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data):
        if not isinstance(data, dict):
            return {"score": None}
        raw_tags = data.get("failure_tags")
        tags = (
            [str(tag) for tag in raw_tags if str(tag) in FAILURE_TAGS][:3]
            if isinstance(raw_tags, list) else []
        )
        return {
            "score": _parse_score(data.get("score")),
            "failure_tags": tags,
            "critique": _compact_critique(_text_value(data.get("critique"))),
            "fix": _compact_fix(data.get("fix")),
            "next_question": _question_text(data),
            "next_topic": str(data.get("next_topic") or "").strip(),
            "concept": str(data.get("concept") or "").strip(),
            "difficulty": str(data.get("difficulty") or "").strip() or None,
            "materially_weak": bool(data.get("materially_weak")),
            "done": bool(data.get("done")),
        }

    @property
    def status(self) -> str:
        """``ok`` when score, critique, and fix are all present; else ``partial``."""
        if self.score is None:
            return "invalid"
        return "ok" if self.critique and self.fix else "partial"


def _evaluation_schema(final_turn: bool, rubric_family: str = "argument") -> dict:
    """Per-turn evaluation schema. The whole-interview review is separate.

    The ``score`` description is the family rubric for this question type, so a
    technical answer is not graded against thesis-shaped criteria. The final
    turn is an ordinary turn: it evaluates the last answer only and never asks
    for a postmortem.
    """
    return {
        "score": RUBRICS[rubric_family][1],
        "failure_tags": "array of 0-3 tag strings",
        "critique": (
            "required string, 1-2 sentences, maximum 60 words: the single most "
            "important weakness, specific to what the candidate actually said"
        ),
        "fix": "required string: one concrete thing to do differently next time",
        "materially_weak": "boolean",
        "next_question": (
            "required string: one candidate-facing question"
            if not final_turn
            else "string: one candidate-facing question, or empty"
        ),
        "next_topic": "string", "concept": "string (underlying concept)",
        "difficulty": "optional string",
    }


def _parse_evaluation_data(raw: str) -> dict:
    """Reject incomplete JSON that the generic chat parser treats as prose."""
    data = parse_json_response(raw)
    expected = {
        "score", "failure_tags", "critique", "materially_weak", "next_question",
        "next_topic", "concept", "difficulty", "done", "postmortem",
    }
    if not any(key in data for key in expected):
        raise ValueError("The interview model response did not contain evaluation fields.")
    return data


def _repair_message(problems: list[str]) -> str:
    detail = "; ".join(problems) or "the response was unusable"
    return (
        f"Your previous response was unusable ({detail}). Return valid JSON only "
        "using the exact required schema, with no preamble or extra fields. "
        "Every required field must be present and correctly typed."
    )


_POSTMORTEM_LIST_ALIASES = {
    "strongest_areas": ("strengths",),
    "biggest_problems": ("weaknesses", "improvements"),
    "concepts_to_repeat": ("next_steps",),
}


def _postmortem_items(raw: dict, key: str, limit: int) -> list[str]:
    """Read a postmortem list, preferring the canonical key and accepting aliases."""
    value = raw.get(key)
    if value in (None, "", []):
        for alias in _POSTMORTEM_LIST_ALIASES.get(key, ()):
            candidate = raw.get(alias)
            if candidate not in (None, "", []):
                value = candidate
                break
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _build_postmortem(data: dict) -> InterviewPostmortem:
    """Turn whatever the model returned into a postmortem with an honest status."""
    raw = data.get("postmortem") if isinstance(data.get("postmortem"), dict) else {}
    overall = str(raw.get("overall_performance") or "").strip()
    strongest = _postmortem_items(raw, "strongest_areas", 3)
    problems = _postmortem_items(raw, "biggest_problems", 3)
    repeat = _postmortem_items(raw, "concepts_to_repeat", 6)
    roots = raw.get("root_causes")
    roots = {str(k): str(v) for k, v in roots.items()} if isinstance(roots, dict) else {}
    if overall and strongest and problems and repeat:
        status = "ok"
    elif overall or strongest or problems or repeat:
        status = "partial"
    else:
        status = "missing"
    return InterviewPostmortem(
        overall_performance=overall,
        biggest_problems=problems,
        strongest_areas=strongest,
        concepts_to_repeat=repeat,
        root_causes=roots,
        trend=str(raw.get("trend") or "").strip(),
        status=status,
    )


_POSTMORTEM_RANK = {"": 0, "missing": 0, "partial": 1, "ok": 2}


def _postmortem_rank(postmortem: InterviewPostmortem | None) -> int:
    return _POSTMORTEM_RANK.get(postmortem.status if postmortem else "", 0)


# Turn evaluation quality for choosing between a first response and its repair.
_EVALUATION_STATUS_RANK = {"invalid": 0, "partial": 1, "ok": 2}


def _read_turn(raw: str) -> tuple[dict, TurnEvaluation, list[str]]:
    """Parse one structured response without raising; report what was wrong."""
    try:
        data = _parse_evaluation_data(raw)
    except (ValueError, json.JSONDecodeError):
        return {}, TurnEvaluation(), ["the response was not valid JSON in the required schema"]
    evaluation = TurnEvaluation.model_validate(data)
    problems: list[str] = []
    if evaluation.score is None:
        problems.append("score missing")
    if not evaluation.critique:
        problems.append("critique empty")
    return data, evaluation, problems


def evaluate_answer(
    session_id: str,
    answer_text: str,
    is_retry: bool = False,
    voice_origin: bool = False,
    provider: LLMProvider | None = None,
) -> tuple[InterviewSession, dict]:
    session = get_session(session_id)
    if session is None or session.status != "active" or not session.questions:
        raise RuntimeError("This practice session is no longer active.")
    question = session.questions[-1]
    final_turn = len(session.questions) >= session.target_questions
    rubric_family = get_preset(session.preset_key, session.mode).rubric_family
    prompt = {
        "task": "Evaluate privately, then decide the single next interviewer move. Finish if final_turn is true.",
        "current_question": question.text,
        "candidate_answer": answer_text.strip(),
        "is_retry": is_retry,
        "final_turn": final_turn,
        "questions_remaining": max(0, session.target_questions - len(session.questions)),
        "recent_context": _recent_context(session),
        "setup": {
            "topic": session.topic, "role": session.role,
            "focus_areas": session.focus_areas, "compact_brief": session.compact_brief,
        },
        "output_schema": _evaluation_schema(final_turn, rubric_family),
    }
    llm = provider or default_provider()
    base_tokens = EVAL_MAX_TOKENS

    def complete(
        user_message: str, *, max_tokens: int, json_mode: bool = True, temperature: float = 0.4,
    ) -> str:
        try:
            return llm.complete(
                [
                    {"role": "system", "content": _system(session, json.dumps(prompt), transcript_note=voice_origin)},
                    {"role": "user", "content": user_message},
                ],
                CompletionOptions(
                    model=session.model or interview_model(), max_tokens=max_tokens,
                    temperature=temperature, json_mode=json_mode,
                ),
            )
        except InterviewOutputError:
            # Empty content is an output problem, not a provider failure. Treat
            # it as an unusable read so the repair/fallback path still runs.
            return ""

    # At most two calls per turn. The single repair is either the structured
    # retry (invalid score or empty critique) or the plain-text question
    # recovery, whichever is needed first.
    repair_used = False
    _, first_evaluation, problems = _read_turn(complete(
        "Make the next interviewer move using the required JSON schema.",
        max_tokens=base_tokens,
    ))
    evaluation = first_evaluation
    if problems:
        repair_used = True
        _, repair_evaluation, _ = _read_turn(complete(
            _repair_message(problems),
            max_tokens=int(base_tokens * REPAIR_TOKEN_FACTOR),
        ))
        first_rank = _EVALUATION_STATUS_RANK.get(first_evaluation.status, 0)
        repair_rank = _EVALUATION_STATUS_RANK.get(repair_evaluation.status, 0)
        if first_rank == 0 and repair_rank == 0:
            raise InterviewOutputError(
                "The interview model returned unusable structured feedback twice."
            )
        # The higher-ranked evaluation wins; a tie prefers the repair.
        if repair_rank >= first_rank:
            evaluation = repair_evaluation
        else:
            evaluation = first_evaluation
        if not evaluation.next_question and first_evaluation.next_question:
            # The chosen response dropped the follow-up the first one supplied.
            evaluation.next_question = first_evaluation.next_question

    done = final_turn
    if not done and not evaluation.next_question:
        if repair_used:
            evaluation.next_question = FALLBACK_FOLLOW_UP
        else:
            repair_used = True
            recovered = parse_json_response(complete(
                "Ask one concise follow-up question only. Return plain text; no JSON, "
                "analysis, score, or preamble.",
                max_tokens=QUESTION_RECOVERY_MAX_TOKENS, json_mode=False, temperature=0.2,
            ))
            evaluation.next_question = _question_text(recovered) or FALLBACK_FOLLOW_UP

    question.answers.append(InterviewAnswer(
        text=answer_text.strip(), score=evaluation.score,
        failure_tags=evaluation.failure_tags, critique=evaluation.critique,
        fix=evaluation.fix, evaluation_status=evaluation.status,
        is_retry=is_retry, voice=voice_origin,
        input_method="voice" if voice_origin else "typed",
    ))
    mark_review(question, evaluation.score, evaluation.failure_tags, is_retry)

    result = {
        "score": evaluation.score,
        "failure_tags": evaluation.failure_tags,
        "critique": evaluation.critique,
        "fix": evaluation.fix,
        "evaluation_status": evaluation.status,
        "materially_weak": evaluation.materially_weak,
        "next_question": evaluation.next_question,
        "next_topic": evaluation.next_topic,
        "concept": evaluation.concept,
        "difficulty": evaluation.difficulty,
        "done": done,
    }
    if done:
        # The final turn is an ordinary turn: the review is written separately
        # by synthesize_session(), so completion only marks the pending state
        # and bumps the View counts (exactly once per session).
        session.postmortem = InterviewPostmortem(status="pending")
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        session.pending_move = {}
        _record_view_counts(session)
    else:
        session.pending_move = result
    save_session(session)
    return session, result


def _record_view_counts(session: InterviewSession) -> None:
    """Bump per-View practice counts on completion, once per session."""
    if not session.view_ids:
        return
    from storage.persistence import load_state, save_state
    state = load_state()
    style = session.practice_style.lower()
    for view in state.topic_views:
        if view.id not in session.view_ids:
            continue
        view.practice.last_practiced = session.completed_at
        view.practice.practice_count += 1
        if style == "deliver":
            view.practice.delivery_attempts += 1
        elif style == "discuss":
            view.practice.discussion_attempts += 1
        elif style == "defend":
            view.practice.defense_attempts += 1
    save_state(state)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize a possibly-naive datetime to aware UTC for comparison."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _is_latest_completed_for_view(session: InterviewSession, view_id: str, database) -> bool:
    """True when no other completed session for this View is newer than this one."""
    here = _as_utc(session.completed_at)
    if here is None:
        return False
    for candidate in database.sessions:
        if candidate.id == session.id or candidate.status != "completed":
            continue
        if view_id not in candidate.view_ids:
            continue
        there = _as_utc(candidate.completed_at)
        if there is not None and there > here:
            return False
    return True


def _record_view_diagnostic(session: InterviewSession) -> None:
    """Write the review's diagnostics onto the View, only with non-empty content.

    Runs after a successful synthesis, and only for a View whose most recent
    completed session is this one: retrying an older session's summary must not
    overwrite the diagnostic written by a newer session. A missing or legacy
    review must not overwrite the last usable diagnostic, and neither must an
    empty one.
    """
    if not session.view_ids or session.postmortem is None:
        return
    diagnostics = (session.postmortem.biggest_problems + session.postmortem.strongest_areas)[:3]
    if not diagnostics:
        return
    database = load_database()
    from storage.persistence import load_state, save_state
    state = load_state()
    changed = False
    for view in state.topic_views:
        if view.id not in session.view_ids:
            continue
        if not _is_latest_completed_for_view(session, view.id, database):
            continue
        view.practice.latest_diagnostic = diagnostics
        changed = True
    if changed:
        save_state(state)


def session_stats(session: InterviewSession) -> dict:
    """Pure end-of-session numbers for the summary and the postmortem stats line.

    Retries are excluded everywhere: coverage is scored first attempts over
    total first attempts, the mean score is over scored first attempts, and tag
    counts come from first attempts only.
    """
    answers = [answer for question in session.questions for answer in question.answers]
    first_attempts = [answer for answer in answers if not answer.is_retry]
    evaluated = [answer for answer in first_attempts if answer.score is not None]
    scores = [answer.score for answer in evaluated]
    band = session_band(session)
    tag_counts = Counter(tag for answer in first_attempts for tag in answer.failure_tags)
    return {
        "first_attempt_count": len(first_attempts),
        "evaluated_count": len(evaluated),
        "coverage": (len(evaluated) / len(first_attempts)) if first_attempts else 0.0,
        "mean_first_attempt_score": (sum(scores) / len(scores)) if scores else None,
        "band": band[0] if band else None,
        "tag_counts": dict(tag_counts),
    }


# The whole-interview review is a separate call after completion. The model is
# given the preset's own end-of-session instructions, the app-computed numbers
# as facts, and one record per answer.
_SYNTHESIS_SYSTEM = (
    "You write the whole-interview review now that the practice session has "
    "ended. You are given the setup, app-computed numbers you must treat as "
    "facts, and one record per answer. Follow the supplied end-of-session "
    "instructions. Cite question numbers. Never invent an answer or a score. "
    "Return JSON only, with no preamble."
)


def _synthesis_records(session: InterviewSession) -> list[dict]:
    """One record per answer; long answers are capped unless the session is short.

    Sessions with three or fewer questions pass full answer text. Longer
    sessions cap each answer at 1,000 characters so the input stays bounded.
    """
    cap = None if len(session.questions) <= 3 else 1000
    records: list[dict] = []
    for number, question in enumerate(session.questions, start=1):
        for answer in question.answers:
            records.append({
                "question": f"Q{number}: {question.text}",
                "attempt": "retry" if answer.is_retry else "first",
                "score": answer.score,
                "failure_tags": list(answer.failure_tags),
                "critique": answer.critique,
                "fix": answer.fix,
                "status": answer.evaluation_status,
                "answer": answer.text if cap is None else answer.text[:cap],
            })
    return records


def _synthesis_prompt(session: InterviewSession) -> dict:
    preset = get_preset(session.preset_key, session.mode)
    stats = session_stats(session)
    return {
        "task": (
            "The interview is over. Write only the whole-interview review from "
            "the records below. Do not ask another question."
        ),
        "setup": {
            "topic": session.topic,
            "role": session.role,
            "preset": preset.label,
            "compact_brief": session.compact_brief,
            "stored_view": session.view_context[:6000],
        },
        "session_stats": {
            "answers_first_attempt": stats["first_attempt_count"],
            "answers_evaluated": stats["evaluated_count"],
            "coverage": stats["coverage"],
            "mean_first_attempt_score": stats["mean_first_attempt_score"],
            "band": stats["band"],
            "most_frequent_tags": [
                tag for tag, _ in Counter(stats["tag_counts"]).most_common(5)
            ],
        },
        "session_stats_note": (
            "These numbers are computed by the app from the answers. Treat them "
            "as facts; do not recompute or contradict them."
        ),
        "end_of_session_instructions": preset.prompt,
        "answers": _synthesis_records(session),
        "output_schema": {
            "overall_performance": "2-4 sentences",
            "strongest_areas": "up to 3, each citing question numbers such as 'Q2, Q5: ...'",
            "biggest_problems": (
                "up to 3, each citing question numbers and starting with one "
                "category: knowledge, evidence, reasoning, communication or pressure"
            ),
            "concepts_to_repeat": "up to 3 concrete next drills",
        },
    }


def _read_synthesis(raw: str) -> tuple[InterviewPostmortem, bool]:
    """Parse a synthesis response into a postmortem; flag an unusable review."""
    try:
        data = parse_json_response(raw)
    except (ValueError, json.JSONDecodeError):
        return InterviewPostmortem(status="missing"), True
    if not isinstance(data, dict):
        return InterviewPostmortem(status="missing"), True
    postmortem = _build_postmortem({"postmortem": data})
    return postmortem, postmortem.status == "missing"


def synthesize_session(
    session_id: str, provider: LLMProvider | None = None,
) -> InterviewSession:
    """Write the whole-interview review for a completed session.

    One call, plus at most one repair at 1.5x the budget. Failures never raise
    to the caller: a provider or output failure is recorded as ``missing`` with
    ``synthesis_error`` set, and the View's diagnostic is left untouched. An
    existing ``ok`` summary is never re-billed, and a usable summary is never
    downgraded.
    """
    session = get_session(session_id)
    if session is None or session.status != "completed":
        raise RuntimeError("Only a completed session can be summarised.")
    if session.postmortem is not None and session.postmortem.status == "ok":
        return session
    llm = provider or default_provider()
    prompt = _synthesis_prompt(session)

    def complete(max_tokens: int) -> str:
        try:
            return llm.complete(
                [
                    {"role": "system", "content": _SYNTHESIS_SYSTEM},
                    {"role": "user", "content": json.dumps(prompt)},
                ],
                CompletionOptions(
                    model=session.model or interview_model(), max_tokens=max_tokens,
                    temperature=0.4, json_mode=True,
                ),
            )
        except InterviewOutputError:
            # Empty content is an output problem, not a provider failure: treat
            # it like malformed output so the single repair still runs and a
            # second empty response records an output failure instead of raising.
            return ""

    try:
        postmortem, malformed = _read_synthesis(complete(SYNTHESIS_MAX_TOKENS))
        if malformed:
            postmortem, malformed = _read_synthesis(
                complete(int(SYNTHESIS_MAX_TOKENS * REPAIR_TOKEN_FACTOR))
            )
    except InterviewProviderError:
        postmortem = InterviewPostmortem(status="missing", synthesis_error="provider")
    else:
        if malformed:
            postmortem = InterviewPostmortem(status="missing", synthesis_error="output")
        else:
            postmortem.synthesis_error = ""

    # Never downgrade: a usable summary stays even if the retry comes back worse.
    if _postmortem_rank(postmortem) >= _postmortem_rank(session.postmortem):
        session.postmortem = postmortem
    if session.postmortem is not None and session.postmortem.status in ("ok", "partial"):
        _record_view_diagnostic(session)
    save_session(session)
    return session


def advance_session(session_id: str, result: dict) -> InterviewSession:
    session = get_session(session_id)
    if session is None or session.status != "active":
        raise RuntimeError("This practice session is no longer active.")
    session.questions.append(_question({
        # Some providers retain the opening-turn field name ("question")
        # despite being asked for "next_question".  _question intentionally
        # accepts both so a valid follow-up cannot be discarded.
        "question": (
            result.get("next_question") or result.get("nextQuestion")
            or result.get("question") or result.get("text")
        ),
        "topic": result.get("next_topic") or session.topic,
        "concept": result.get("concept"),
        "difficulty": result.get("difficulty"),
    }, session.topic))
    session.pending_move = {}
    save_session(session)
    return session


def abandon_session(session_id: str) -> InterviewSession:
    """End a session without scoring it or recording View-practice metadata."""
    session = get_session(session_id)
    if session is None or session.status != "active":
        raise RuntimeError("This practice session is no longer active.")
    session.status = "abandoned"
    session.completed_at = datetime.now(timezone.utc)
    session.pending_move = {}
    save_session(session)
    return session


def answer_tips(
    session_id: str,
    answer_text: str,
    provider: LLMProvider | None = None,
) -> str:
    """Coach a draft without evaluating, saving, or advancing the session."""
    session = get_session(session_id)
    if session is None or session.status != "active" or not session.questions:
        raise RuntimeError("This practice session is no longer active.")
    draft = answer_text.strip()
    if not draft:
        raise ValueError("Write a draft before requesting tips.")
    question = session.questions[-1]
    prompt = {
        "current_question": question.text,
        "draft_answer": draft,
        "session_topic": session.topic,
        "stored_view_context": session.view_context[:6000],
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [
            {"role": "system", "content": (
                "You are a concise interview-answer coach. Give exactly 3 short, actionable "
                "tips for improving the candidate's draft before they submit it. Prioritize: "
                "(1) answering the question up front and structure, (2) missing causal mechanism "
                "or reasoning, and (3) evidence, caveat, or likely pushback when relevant. Do not "
                "score the answer, ask another question, or write a replacement answer. The stored "
                "View context is optional secondary reference material; it may be stale, so do not "
                "treat it as authoritative or force it into the answer. Return plain text with three "
                "numbered tips only."
            )},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        CompletionOptions(
            model=session.model or interview_model(), max_tokens=300,
            temperature=0.25, json_mode=False,
        ),
    )
    return raw.strip()


def reference_answer(
    session_id: str,
    provider: LLMProvider | None = None,
) -> str:
    """Return (and cache) a model answer that would score 7-8 on the rubric.

    Strictly click-gated by the UI: this is the only path that produces a model
    answer, and only after the session is over. The result is cached on the
    session so a re-render never re-bills the extra call.
    """
    session = get_session(session_id)
    if session is None or session.status != "completed":
        raise RuntimeError("A reference answer is only available after a completed session.")
    if session.reference_answer:
        return session.reference_answer
    answer_text = ""
    for question in session.questions:
        if question.answers:
            answer_text = question.answers[0].text
            break
    if not answer_text:
        raise RuntimeError("This session has no answer to reference.")
    prompt = {
        "topic": session.topic,
        "stored_view": session.view_context[:6000],
        "candidate_answer": answer_text[:4000],
        "target_rubric": RUBRICS[rubric_family_for(session)][1],
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [
            {"role": "system", "content": (
                "You are a demanding interview coach. Write one reference answer that would "
                "score 7-8 on the rubric supplied in target_rubric for the given topic, using "
                "the stored View as background. Speak it as if answering the question aloud in "
                "150-200 words: bottom line first, one causal chain explained end to end, "
                "evidence with magnitudes, and what would falsify the view. Do not invent facts "
                "that neither the stored View nor general knowledge supports. Then, under the "
                "heading 'What the strong version does differently', list exactly two or three "
                "short structural differences from the candidate's answer (not word-level edits). "
                "Return plain text only."
            )},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        CompletionOptions(
            model=session.model or interview_model(), max_tokens=650,
            temperature=0.3, json_mode=False,
        ),
    )
    text = raw.strip()
    if not text:
        raise RuntimeError("The interview model did not return a reference answer.")
    session.reference_answer = text
    save_session(session)
    return text
