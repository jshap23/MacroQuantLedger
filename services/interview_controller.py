from __future__ import annotations

import json
from datetime import datetime, timezone

from models.interview import InterviewAnswer, InterviewPostmortem, InterviewQuestion, InterviewSession
from services.interview_llm import (
    CompletionOptions, FAILURE_TAGS, LLMProvider, default_provider,
    interview_model, parse_json_response,
)
from storage.interview_store import get_session, mark_review, save_session, weakness_context


BASE_RULES = """You are an AI interview sparring partner: a demanding professional interviewer, PM, researcher, economist, investor, or quant—not a tutor.
Ask exactly one short question at a time (prefer under 30 words). Make the candidate do most of the talking. Never hint before an answer. Never say generic phrases such as 'Great answer', 'interesting perspective', or 'let's unpack that'. Follow up on what was actually said instead of walking mechanically through a question bank. Challenge vague claims. Ask for mechanisms behind causal claims, evidence behind empirical claims, and quantification where useful. If the candidate dodges, repeat the question more directly. If they ramble, interrupt and request a shorter answer. If they do not know, ask them to reason from first principles. Do not lecture unless explicitly requested.

Valid failure tags only: ANSWER_FIRST, RAMBLE, DID_NOT_ANSWER, KNOWLEDGE_GAP, EVIDENCE_GAP, WEAK_MECHANISM, UNSUPPORTED_ASSERTION, FAILED_PUSHBACK, IMPLEMENTATION_GAP, TOO_HEDGED, OVERCONFIDENT.
Tag meanings: ANSWER_FIRST means the candidate failed to lead with the answer; RAMBLE means needlessly long or unstructured; DID_NOT_ANSWER means the response dodged the question; KNOWLEDGE_GAP means missing required domain knowledge; EVIDENCE_GAP means an empirical claim lacks evidence; WEAK_MECHANISM means causality was asserted but not explained; UNSUPPORTED_ASSERTION means a material claim has no support; FAILED_PUSHBACK means the answer broke under challenge; IMPLEMENTATION_GAP means the candidate cannot translate the idea into concrete implementation; TOO_HEDGED means excessive qualification obscures the view; OVERCONFIDENT means certainty exceeds the evidence.
Return JSON only. Do not put multiple questions in any question field."""


MODE_RULES = {
    "Discussion": "Hold an intellectually serious conversation across 2–3 substantive topics. Challenge assumptions and introduce counterarguments. Do not show scoring or coach every response.",
    "Drill": "Ask focused interview questions. Evaluate each answer with a 1–10 score, at most two failure tags, and critique of no more than two sentences and 60 words. A score of 5 or below is materially weak. Never provide a model answer.",
    "Simulation": "Conduct a realistic interview. Candidate-facing output must contain no scores, coaching, hints, compliments, or explanations. Follow up, challenge, change topics, and occasionally interrupt long answers.",
    "Research Defense": "Apply hostile scrutiny to claims in the supplied research, resume, presentation, model, or thesis. Probe evidence, sample, causality, robustness, falsification, out-of-sample results, competing explanations, and implementation choices. Scrutinize volunteered claims especially aggressively.",
}


def _system(mode: str) -> str:
    return f"{BASE_RULES}\n\nMODE: {mode}\n{MODE_RULES[mode]}"


def _question(data: dict, fallback_topic: str) -> InterviewQuestion:
    text = str(data.get("question") or data.get("next_question") or "").strip()
    if not text:
        raise RuntimeError("The interview model did not return a question.")
    return InterviewQuestion(
        text=text,
        topic=str(data.get("topic") or fallback_topic).strip(),
        concept=str(data.get("concept") or "").strip(),
        difficulty=str(data.get("difficulty") or "").strip() or None,
    )


def start_session(
    mode: str,
    topic: str,
    role: str = "",
    focus_areas: str = "",
    materials: str = "",
    target_questions: int = 10,
    weakness_session: bool = False,
    model: str = "",
    provider: LLMProvider | None = None,
) -> InterviewSession:
    session = InterviewSession(
        mode=mode,
        topic=topic.strip() or "General professional interview",
        role=role.strip(),
        focus_areas=focus_areas.strip(),
        materials=materials.strip(),
        target_questions=max(1, min(50, int(target_questions))),
        weakness_session=weakness_session,
        model=interview_model(model),
    )
    setup = {
        "task": "Start the session with one question.",
        "topic": session.topic,
        "role": session.role,
        "focus_areas": session.focus_areas,
        "materials": session.materials[:6000],
        "target_questions": session.target_questions,
        "weakness_context": weakness_context() if weakness_session else "",
        "output_schema": {
            "question": "string", "topic": "string", "concept": "string",
            "difficulty": "optional string",
            "session_brief": "under 120 words: claims/topics to revisit; no coaching",
        },
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [{"role": "system", "content": _system(mode)}, {"role": "user", "content": json.dumps(setup)}],
        CompletionOptions(model=session.model, max_tokens=220),
    )
    data = parse_json_response(raw)
    session.questions.append(_question(data, session.topic))
    session.compact_brief = str(data.get("session_brief") or session.materials[:1200]).strip()
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


def evaluate_answer(
    session_id: str,
    answer_text: str,
    is_retry: bool = False,
    provider: LLMProvider | None = None,
) -> tuple[InterviewSession, dict]:
    session = get_session(session_id)
    if session is None or session.status != "active" or not session.questions:
        raise RuntimeError("This practice session is no longer active.")
    question = session.questions[-1]
    final_turn = len(session.questions) >= session.target_questions
    prompt = {
        "task": "Evaluate privately, then decide the single next interviewer move. Finish if final_turn is true.",
        "current_question": question.text,
        "candidate_answer": answer_text.strip(),
        "is_retry": is_retry,
        "final_turn": final_turn,
        "recent_context": _recent_context(session),
        "setup": {
            "topic": session.topic, "role": session.role,
            "focus_areas": session.focus_areas, "compact_brief": session.compact_brief,
        },
        "output_schema": {
            "score": "integer 1-10; hidden by UI outside Drill",
            "failure_tags": "array, maximum 2",
            "critique": "maximum 2 sentences and 60 words; empty outside Drill",
            "materially_weak": "boolean",
            "next_question": "one candidate-facing question, or empty if done",
            "next_topic": "string", "concept": "underlying concept", "difficulty": "optional string",
            "done": "boolean",
            "postmortem": {
                "overall_performance": "brief", "biggest_problems": "max 3",
                "strongest_areas": "max 3", "concepts_to_repeat": "short list",
                "root_causes": {"knowledge": "", "evidence/research": "", "reasoning": "", "communication": "", "pressure handling": ""},
            },
        },
    }
    llm = provider or default_provider()
    raw = llm.complete(
        [{"role": "system", "content": _system(session.mode)}, {"role": "user", "content": json.dumps(prompt)}],
        CompletionOptions(model=session.model or interview_model(), max_tokens=650 if final_turn else 350),
    )
    data = parse_json_response(raw)
    try:
        score = max(1, min(10, int(data.get("score"))))
    except (TypeError, ValueError):
        score = None
    raw_tags = data.get("failure_tags") if isinstance(data.get("failure_tags"), list) else []
    tags = [str(tag) for tag in raw_tags if str(tag) in FAILURE_TAGS][:2]
    critique = _compact_critique(data.get("critique"))
    question.answers.append(InterviewAnswer(
        text=answer_text.strip(), score=score, failure_tags=tags,
        critique=critique, is_retry=is_retry,
    ))
    mark_review(question, score, tags, is_retry)

    done = bool(data.get("done")) or final_turn
    data.update({"score": score, "failure_tags": tags, "critique": critique, "done": done})
    if done:
        raw_postmortem = data.get("postmortem") if isinstance(data.get("postmortem"), dict) else {}
        def strings(key: str, limit: int = 3) -> list[str]:
            value = raw_postmortem.get(key, [])
            if isinstance(value, str):
                value = [value]
            return [str(item).strip() for item in value if str(item).strip()][:limit] if isinstance(value, list) else []

        roots = raw_postmortem.get("root_causes")
        roots = {str(k): str(v) for k, v in roots.items()} if isinstance(roots, dict) else {}
        session.postmortem = InterviewPostmortem(
            overall_performance=str(raw_postmortem.get("overall_performance") or "Session completed.").strip(),
            biggest_problems=strings("biggest_problems"),
            strongest_areas=strings("strongest_areas"),
            concepts_to_repeat=strings("concepts_to_repeat", 6),
            root_causes=roots,
        )
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        session.pending_move = {}
    else:
        session.pending_move = {
            key: data.get(key) for key in (
                "score", "failure_tags", "critique", "materially_weak",
                "next_question", "next_topic", "concept", "difficulty", "done",
            )
        }
    save_session(session)
    return session, data


def advance_session(session_id: str, result: dict) -> InterviewSession:
    session = get_session(session_id)
    if session is None or session.status != "active":
        raise RuntimeError("This practice session is no longer active.")
    session.questions.append(_question({
        "question": result.get("next_question"),
        "topic": result.get("next_topic") or session.topic,
        "concept": result.get("concept"),
        "difficulty": result.get("difficulty"),
    }, session.topic))
    session.pending_move = {}
    save_session(session)
    return session
