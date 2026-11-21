"""Standalone validation script for interview practice persistence and fixes.

Run with: python validate_interview_practice.py

All scenarios use temporary directories; the live data/interview_history.json is
never touched. Cases 1-3 cover Task 1 (never lose history when the file is
unreadable); cases 4-14 cover the validated per-turn evaluation, the
single-repair call budget (Tasks 2 and 3), provider-vs-output failures
(Task 4), controller-owned session end (Task 5), and honest postmortems
(Tasks 6 and 7).
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from models.interview import (
    InterviewAnswer, InterviewDatabase, InterviewPostmortem, InterviewQuestion,
    InterviewSession,
)
from models.schema import TopicView, default_state
from services import interview_controller as controller
from services.interview_controller import (
    EVAL_MAX_TOKENS,
    FALLBACK_FOLLOW_UP,
    RUBRICS,
    SYNTHESIS_MAX_TOKENS,
    _evaluation_schema,
    band_visible,
    evaluate_answer,
    reference_answer,
    rubric_bands,
    session_band,
    session_stats,
    start_session,
    synthesize_session,
)
from services.fact_check import fact_check_session
from services.interview_llm import (
    CompletionOptions, InterviewOutputError, InterviewProviderError,
    OpenAICompatibleProvider,
)
from services.interview_prompts import (
    LEGACY_V2_PROMPT_PACK, PRESETS, PROMPT_PACK_VERSION,
)
import storage.persistence as persistence
from storage import interview_store as store
from storage.interview_store import (
    InterviewHistoryUnreadable,
    comparability_key,
    effective_input_method,
    effective_rubric_id,
    load_database,
    model_practice_stats,
    performance_summary,
    save_preferred_model,
    save_session,
    trend_eligible,
    trend_session_count,
    view_practice_stats,
)


def _temp_history_file() -> Path:
    tmp = Path(tempfile.mkdtemp())
    return tmp / "interview_history.json"


def _patch_history_file(path: Path) -> None:
    store.INTERVIEW_FILE = path


def _backups_for(path: Path) -> list[Path]:
    return sorted((path.parent / "backups").glob("interview_history_unreadable_*.json"))


_STATE_HOLDER: dict = {}


def _install_state_stub() -> None:
    """Redirect View-metadata persistence to an in-memory state for the run.

    The controller imports ``load_state``/``save_state`` at call time, so
    replacing the module attributes keeps the live ``data/state.json`` untouched.
    """
    _STATE_HOLDER["json"] = default_state().model_dump_json()

    def fake_load():
        return persistence.AppState.model_validate_json(_STATE_HOLDER["json"])

    def fake_save(state):
        _STATE_HOLDER["json"] = state.model_dump_json()

    persistence.load_state = fake_load
    persistence.save_state = fake_save


def _seed_view(view_id: str) -> None:
    state = persistence.AppState.model_validate_json(_STATE_HOLDER["json"])
    state.topic_views.append(TopicView(id=view_id, name="Test View"))
    _STATE_HOLDER["json"] = state.model_dump_json()


def _view_practice(view_id: str):
    state = persistence.AppState.model_validate_json(_STATE_HOLDER["json"])
    return next((view.practice for view in state.topic_views if view.id == view_id), None)


def _legacy_payload() -> dict:
    """A file as written by the pre-Task-2 schema.

    Answers carry no ``fix``/``evaluation_status`` and the postmortem keeps the
    old ``"Session completed."`` default text.
    """
    return {
        "preferred_model": "z-ai/glm-5.3",
        "sessions": [
            {
                "id": "legacy-session-1",
                "mode": "Drill",
                "topic": "Term premium",
                "status": "completed",
                "questions": [
                    {
                        "id": "q1",
                        "text": "What drives the term premium?",
                        "answers": [
                            {
                                "text": "Supply and policy uncertainty.",
                                "score": 6,
                                "failure_tags": ["hand-waving"],
                                "critique": "Mechanism was asserted, not shown.",
                            }
                        ],
                    }
                ],
                "postmortem": {
                    "overall_performance": "Session completed.",
                    "biggest_problems": [],
                    "strongest_areas": [],
                    "concepts_to_repeat": [],
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# Fake provider harness for the controller tests.
# ---------------------------------------------------------------------------


class FakeProvider:
    """Returns scripted strings (or raises scripted exceptions) and records calls."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, messages, options: CompletionOptions) -> str:
        self.calls.append({"messages": messages, "options": options})
        if not self.responses:
            raise AssertionError("FakeProvider ran out of scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


MARK_REVIEW_SCORES: list[int | None] = []


def _install_controller_stubs() -> None:
    """Stub history-dependent context and spy on mark_review for the run."""
    controller.weakness_context = lambda: ""
    _install_state_stub()
    real_mark_review = controller.mark_review

    def spy(question, score, tags, is_retry):
        MARK_REVIEW_SCORES.append(score)
        return real_mark_review(question, score, tags, is_retry)

    controller.mark_review = spy


def _new_session(**overrides) -> InterviewSession:
    """Start a non-final Drill session against a fresh temp history file."""
    _patch_history_file(_temp_history_file())
    params = {
        "mode": "Drill", "topic": "Term premium", "preset_key": "quant_drill",
        "model": "test-model", "target_questions": 6,
    }
    params.update(overrides)
    return start_session(**params)


def _json(payload: dict) -> str:
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Task 1: never lose history.
# ---------------------------------------------------------------------------


def test_unreadable_history_is_backed_up_not_wiped() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    payload = _legacy_payload()
    payload["sessions"][0]["status"] = "needs_review"  # not a valid Literal
    original = json.dumps(payload, indent=2).encode("utf-8")
    history.write_bytes(original)

    raised: InterviewHistoryUnreadable | None = None
    try:
        load_database()
    except InterviewHistoryUnreadable as exc:
        raised = exc
    assert raised is not None, "load_database must not swallow an invalid history file"
    assert raised.source == history
    assert raised.backup.exists()
    assert raised.backup.read_bytes() == original
    assert history.read_bytes() == original, "original file must be byte-identical"
    assert _backups_for(history) == [raised.backup]

    # A following save must not overwrite the unreadable file.
    session = InterviewSession(mode="Drill", topic="Rates")
    try:
        save_session(session)
    except InterviewHistoryUnreadable:
        pass
    else:
        raise AssertionError("save_session must refuse to overwrite an unreadable history")
    assert history.read_bytes() == original
    # save_session went through load_database again: an identical file must
    # reuse its existing backup rather than writing another.
    assert _backups_for(history) == [raised.backup], "identical unreadable file must reuse its backup"
    print("PASS: unreadable history is backed up and never overwritten")


def test_undecodable_history_is_backed_up() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    original = b"\xff\xfe\x00\x00 not valid utf-8"
    history.write_bytes(original)

    raised: InterviewHistoryUnreadable | None = None
    try:
        load_database()
    except InterviewHistoryUnreadable as exc:
        raised = exc
    assert raised is not None, "an undecodable history file must not be treated as empty"
    assert raised.source == history
    assert raised.backup.exists()
    assert raised.backup.read_bytes() == original
    assert history.read_bytes() == original
    print("PASS: undecodable history is backed up, not treated as empty")


def test_missing_history_returns_empty_and_first_save_creates_file() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    assert not history.exists()

    database = load_database()
    assert isinstance(database, InterviewDatabase)
    assert database.sessions == []
    assert database.preferred_model == ""

    session = InterviewSession(mode="Drill", topic="Rates")
    save_session(session)
    assert history.exists()
    reloaded = load_database()
    assert [s.id for s in reloaded.sessions] == [session.id]
    print("PASS: missing history loads empty; first save creates the file")


def test_legacy_history_loads_without_error() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    history.write_text(json.dumps(_legacy_payload(), indent=2), encoding="utf-8")

    database = load_database()
    session = database.sessions[0]
    assert session.status == "completed"
    answer = session.questions[0].answers[0]
    assert answer.score == 6
    assert answer.failure_tags == ["hand-waving"]
    assert answer.critique == "Mechanism was asserted, not shown."
    assert answer.fix == ""
    assert answer.evaluation_status == ""
    postmortem = session.postmortem
    assert postmortem is not None
    assert postmortem.overall_performance == "Session completed."
    # InterviewPostmortem.status arrives in Task 6; stay tolerant until then.
    assert getattr(postmortem, "status", "") == ""
    print("PASS: legacy history loads without error")


# ---------------------------------------------------------------------------
# Tasks 2 and 3: validated evaluation and one repair per turn.
# ---------------------------------------------------------------------------


def test_incomplete_evaluation_twice_raises_and_saves_nothing() -> None:
    session = _new_session()
    provider = FakeProvider([_json({"next_question": "Why?"})] * 2)
    try:
        evaluate_answer(session.id, "My answer.", provider=provider)
    except InterviewOutputError:
        pass
    else:
        raise AssertionError("an incomplete evaluation twice must raise InterviewOutputError")
    assert len(provider.calls) == 2
    reloaded = load_database()
    stored = next(s for s in reloaded.sessions if s.id == session.id)
    assert stored.questions[-1].answers == []
    print("PASS: incomplete evaluation twice raises and saves nothing")


def test_valid_evaluation_saves_ok_in_one_call() -> None:
    session = _new_session()
    provider = FakeProvider([_json({
        "score": "7/10",
        "critique": "Mechanism was asserted, not shown.",
        "fix": "State the causal chain before the conclusion.",
        "next_question": "What evidence supports that?",
    })])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 1
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 7
    assert answer.evaluation_status == "ok"
    assert answer.fix == "State the causal chain before the conclusion."
    assert result["done"] is False
    print("PASS: valid evaluation saves score 7 as ok in one call")


def test_empty_critique_triggers_one_repair_with_1_5x_budget() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "Do X.", "next_question": "Why?"}),
        _json({"score": 7, "critique": "Say the mechanism.", "fix": "Do X.", "next_question": "Why?"}),
    ])
    updated, _ = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    first, retry = provider.calls
    assert first["options"].max_tokens == EVAL_MAX_TOKENS
    assert retry["options"].max_tokens == int(EVAL_MAX_TOKENS * 1.5)
    assert updated.questions[-1].answers[-1].evaluation_status == "ok"
    print("PASS: empty critique triggers one repair at 1.5x budget")


def test_empty_critique_twice_saves_partial() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 6, "critique": "", "fix": "", "next_question": "Why?"}),
        _json({"score": 6, "critique": "", "fix": "", "next_question": "Why?"}),
    ])
    updated, _ = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 6
    assert answer.evaluation_status == "partial"
    print("PASS: score with no critique on both calls saves as partial")


def test_unusable_repair_keeps_the_first_partial_and_its_question() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "", "next_question": "What evidence supports that?"}),
        "not valid json at all",
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 7
    assert answer.evaluation_status == "partial"
    assert result["next_question"] == "What evidence supports that?"
    assert updated.pending_move["next_question"] == "What evidence supports that?"
    print("PASS: unusable repair keeps the first partial evaluation and its question")


def test_repair_empty_response_keeps_first_valid_score() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "Do X.", "next_question": "Why?"}),
        InterviewOutputError("empty content"),
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    assert answer.score == 7
    assert answer.evaluation_status == "partial"
    assert result["next_question"] == "Why?"
    print("PASS: an empty repair response keeps the first valid score and its question")


def test_recovery_empty_response_falls_back_to_follow_up() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "Fine.", "fix": "Do X."}),
        InterviewOutputError("empty content"),
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    assert updated.questions[-1].answers[-1].score == 7
    assert result["next_question"] == FALLBACK_FOLLOW_UP
    print("PASS: an empty recovery response falls back to FALLBACK_FOLLOW_UP")


def test_provider_failure_during_repair_aborts_the_turn() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "Do X.", "next_question": "Why?"}),
        InterviewProviderError("rate limited"),
    ])
    try:
        evaluate_answer(session.id, "My answer.", provider=provider)
    except InterviewProviderError:
        pass
    else:
        raise AssertionError("a provider failure during repair must abort the turn")
    reloaded = load_database()
    stored = next(s for s in reloaded.sessions if s.id == session.id)
    assert stored.questions[-1].answers == []
    print("PASS: a provider failure during repair aborts the turn and saves nothing")


def test_malformed_then_valid_without_question_uses_fallback() -> None:
    session = _new_session()
    provider = FakeProvider([
        "not valid json at all",
        _json({"score": 7, "critique": "Mechanism missing.", "fix": "Show the chain."}),
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    assert result["next_question"] == FALLBACK_FOLLOW_UP
    assert updated.pending_move["next_question"] == FALLBACK_FOLLOW_UP
    print("PASS: malformed JSON then valid without a question uses FALLBACK_FOLLOW_UP")


def test_model_done_flag_cannot_end_a_session_early() -> None:
    session = _new_session(mode="Discussion", preset_key="view_discuss", target_questions=6)
    provider = FakeProvider([_json({
        "score": 7, "critique": "Clear view.", "fix": "Add evidence.",
        "next_question": "Why does that matter?", "done": True,
    })])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert result["done"] is False
    assert updated.status == "active"
    assert "questions_remaining" in provider.calls[0]["messages"][0]["content"]
    assert updated.pending_move["next_question"] == "Why does that matter?"
    print("PASS: a model done flag cannot end a session early; questions_remaining is sent")


def test_rank_picks_the_higher_ranked_evaluation() -> None:
    session = _new_session()
    provider = FakeProvider([
        _json({"score": 7, "critique": "", "fix": "", "next_question": "First question?"}),
        _json({
            "score": 6, "critique": "Repair critique.", "fix": "Repair fix.",
            "next_question": "Repair question?",
        }),
    ])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 2
    answer = updated.questions[-1].answers[-1]
    # The first is 'partial' (empty critique); the repair is 'ok' and wins.
    assert answer.evaluation_status == "ok"
    assert answer.critique == "Repair critique."
    assert result["next_question"] == "Repair question?"
    print("PASS: the higher-ranked evaluation wins; a tie prefers the repair")


class _ExplodingCompletions:
    def create(self, **kwargs):
        raise ConnectionError("connection reset by peer")


class _ExplodingChat:
    completions = _ExplodingCompletions()


class _ExplodingClient:
    chat = _ExplodingChat()


class ProviderFailureProvider:
    """Simulates a provider whose transport call raises."""

    def __init__(self):
        self.calls = 0

    def complete(self, messages, options):
        self.calls += 1
        raise InterviewProviderError("connection reset by peer")


def test_sdk_failure_is_wrapped_as_provider_error() -> None:
    provider = object.__new__(OpenAICompatibleProvider)
    provider.client = _ExplodingClient()
    try:
        provider.complete([{"role": "user", "content": "hi"}], CompletionOptions(model="test"))
    except InterviewProviderError:
        pass
    else:
        raise AssertionError("an SDK failure must surface as InterviewProviderError")
    print("PASS: SDK failure is wrapped as InterviewProviderError")


def test_provider_failure_surfaces_and_saves_nothing() -> None:
    session = _new_session()
    provider = ProviderFailureProvider()
    try:
        evaluate_answer(session.id, "My answer.", provider=provider)
    except InterviewProviderError:
        pass
    else:
        raise AssertionError("a provider failure must surface as InterviewProviderError")
    assert provider.calls == 1
    reloaded = load_database()
    stored = next(s for s in reloaded.sessions if s.id == session.id)
    assert stored.questions[-1].answers == []
    print("PASS: provider failure surfaces and saves nothing")


def test_turn_schema_requires_fix_and_drops_empty_outside_drill() -> None:
    # The schema is preset-independent; iterating documents that no preset can
    # reintroduce the old "empty outside Drill" wording or drop the fix field.
    for key in PRESETS:
        schema = _evaluation_schema(final_turn=False)
        text = json.dumps(schema)
        assert "empty outside Drill" not in text, key
        assert "fix" in schema, key
        assert schema["failure_tags"] == "array of 0-3 tag strings", key
    print("PASS: every preset's turn-1 schema requires fix and drops 'empty outside Drill'")


def test_session_band_excludes_retries_and_hides_when_missing() -> None:
    def answer(score, is_retry=False):
        return InterviewAnswer(text="x", score=score, is_retry=is_retry)

    session = InterviewSession(
        mode="Drill", topic="Term premium", status="completed",
        prompt_pack_version=PROMPT_PACK_VERSION,
        questions=[InterviewQuestion(text="q", answers=[answer(8), answer(2, is_retry=True)])],
        postmortem=InterviewPostmortem(
            overall_performance="ok", biggest_problems=["p"], strongest_areas=["s"],
            concepts_to_repeat=["c"], status="ok",
        ),
    )
    band = session_band(session)
    assert band is not None
    # Average of first attempts is 8. Including the retry's 2 would make it 5-6.
    assert band[0] == "7-8", band

    session.postmortem.status = "missing"
    assert session_band(session) is None
    print("PASS: band excludes retries and hides when the postmortem is missing")


def test_mark_review_never_receives_a_missing_score() -> None:
    assert MARK_REVIEW_SCORES, "expected at least one scored answer from cases 4-8"
    assert all(score is not None for score in MARK_REVIEW_SCORES), MARK_REVIEW_SCORES
    print("PASS: mark_review never received a missing score")


# ---------------------------------------------------------------------------
# Phase 2 batch A (Tasks 1-2): provenance, comparability, and rubric families.
# ---------------------------------------------------------------------------


def test_p1_legacy_rubric_ids_and_history_untouched() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    payload = {
        "preferred_model": "z-ai/glm-5.3",
        "sessions": [
            {
                "id": "p1-v2", "mode": "Drill", "topic": "Term premium",
                "status": "completed", "prompt_pack_version": LEGACY_V2_PROMPT_PACK,
            },
            {
                "id": "p1-old", "mode": "Drill", "topic": "Rates",
                "status": "completed", "prompt_pack_version": "2025.01.01-v1",
            },
        ],
    }
    history.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    before = history.read_bytes()

    database = load_database()
    by_id = {session.id: session for session in database.sessions}
    assert by_id["p1-v2"].rubric_id == "", "a legacy session must load with no stored rubric_id"
    assert effective_rubric_id(by_id["p1-v2"]) == "shared-v2"
    assert effective_rubric_id(by_id["p1-old"]) == "unanchored"
    assert history.read_bytes() == before, "reading must never rewrite the history file"
    print("PASS: P1 legacy rubric ids derive as shared-v2 / unanchored and history is byte-identical")


def test_p2_input_method_derives_and_records() -> None:
    assert effective_input_method(InterviewAnswer(text="legacy", voice=True)) == "voice"
    assert effective_input_method(InterviewAnswer(text="typed")) == "typed"

    session = _new_session()
    provider = FakeProvider([_json({
        "score": 7, "critique": "Mechanism missing.", "fix": "Show the chain.",
        "next_question": "Why?",
    })])
    updated, _ = evaluate_answer(
        session.id, "My spoken answer.", voice_origin=True, provider=provider,
    )
    answer = updated.questions[-1].answers[-1]
    assert answer.input_method == "voice", "a voice-origin answer must store input_method=voice"
    assert answer.voice is True
    assert effective_input_method(answer) == "voice"
    assert comparability_key(updated, answer) == (
        "technical-v3", "test-model", "quant_drill", "voice",
    )
    print("PASS: P2 input method derives from voice and new answers store it")


def test_p3_trend_eligible_rejects_incomparable_answers() -> None:
    def session_with(**answer_kwargs) -> tuple[InterviewSession, InterviewAnswer]:
        answer = InterviewAnswer(text="x", **answer_kwargs)
        session = InterviewSession(
            mode="Drill", topic="Term premium", status="completed",
            rubric_id="argument-v3",
            questions=[InterviewQuestion(text="q", answers=[answer])],
        )
        return session, answer

    cases = {
        "retry": session_with(score=7, is_retry=True),
        "no score": session_with(score=None),
        "active session": (
            InterviewSession(
                mode="Drill", topic="Term premium", status="active",
                rubric_id="argument-v3",
                questions=[InterviewQuestion(
                    text="q", answers=[InterviewAnswer(text="x", score=7)],
                )],
            ),
            None,
        ),
    }
    for label, (session, answer) in cases.items():
        answer = answer or session.questions[0].answers[0]
        assert not trend_eligible(session, answer), label

    custom, custom_answer = session_with(score=8)
    custom.rubric_id = "custom"
    assert not trend_eligible(custom, custom_answer), "custom session"

    unanchored, unanchored_answer = session_with(score=8)
    unanchored.rubric_id = "unanchored"
    assert not trend_eligible(unanchored, unanchored_answer), "unanchored session"

    eligible, eligible_answer = session_with(score=7)
    assert trend_eligible(eligible, eligible_answer), "a scored non-retry v3 answer is eligible"
    print("PASS: P3 trend_eligible is false for retries, missing scores, custom, unanchored, and active")


def test_p4_presets_have_a_family_and_family_rubric() -> None:
    families = {"argument", "technical", "interview"}

    def normalized(text: str) -> str:
        return " ".join(text.split())

    seven_eight = {
        family: normalized(rubric_bands(family)[3][1]) for family in families
    }
    assert len(set(seven_eight.values())) == 3, "each family needs a distinct 7-8 line"
    for key, preset in PRESETS.items():
        family = preset.rubric_family
        assert family in families, f"{key} has rubric_family={family!r}"
        schema = _evaluation_schema(final_turn=False, rubric_family=family)
        score_desc = normalized(schema["score"])
        assert seven_eight[family] in score_desc, f"{key} schema must carry its own 7-8 line"
        for other in families - {family}:
            assert seven_eight[other] not in score_desc, f"{key} schema leaked {other}'s 7-8 line"
    print("PASS: P4 every preset carries its own family's 7-8 line and not the others'")


def test_p5_start_session_stores_family_rubric_id() -> None:
    _patch_history_file(_temp_history_file())
    argument = start_session(
        mode="Discussion", topic="Term premium", preset_key="view_deliver", target_questions=3,
    )
    technical = start_session(
        mode="Drill", topic="Term premium", preset_key="quant_drill", target_questions=3,
    )
    interview = start_session(
        mode="Simulation", topic="Term premium", preset_key="job_interview", target_questions=3,
    )
    custom = start_session(
        mode="Discussion", topic="Term premium", preset_key="view_deliver",
        target_questions=3, prompt_override="Act as my own interviewer.",
    )
    assert argument.rubric_id == "argument-v3"
    assert technical.rubric_id == "technical-v3"
    assert interview.rubric_id == "interview-v3"
    assert custom.rubric_id == "custom", "a prompt override must be marked custom"
    print("PASS: P5 start_session stores each family rubric id and custom for overrides")


def test_p6_band_gate_keeps_phase1_and_hides_incomparable() -> None:
    assert PROMPT_PACK_VERSION != LEGACY_V2_PROMPT_PACK, "Task 2 must bump the prompt pack"

    def session(**overrides) -> InterviewSession:
        params = {
            "mode": "Drill", "topic": "Term premium", "status": "completed",
            "prompt_pack_version": LEGACY_V2_PROMPT_PACK,
            "questions": [InterviewQuestion(
                text="q", answers=[InterviewAnswer(text="x", score=8)],
            )],
            "postmortem": InterviewPostmortem(
                overall_performance="ok", biggest_problems=["p"],
                strongest_areas=["s"], concepts_to_repeat=["c"], status="ok",
            ),
        }
        params.update(overrides)
        return InterviewSession(**params)

    phase1 = session()
    assert band_visible(phase1), "a Phase 1 anchored session still shows its band"
    assert session_band(phase1) is not None

    assert not band_visible(session(prompt_override="Custom.")), "custom sessions hide the band"
    assert not band_visible(session(prompt_pack_version="2025.01.01-v1")), \
        "unanchored sessions hide the band"

    technical = session(rubric_id="technical-v3", prompt_pack_version=PROMPT_PACK_VERSION)
    technical_band = session_band(technical)
    assert technical_band is not None
    assert "Correct result or method" in technical_band[1], "band text must use the session's family"
    print("PASS: P6 band shows for Phase 1, hides for incomparable, and uses the family band text")


# ---------------------------------------------------------------------------
# Phase 2 batch B (Task 3): separate end-of-interview synthesis.
# ---------------------------------------------------------------------------


def _answer(
    text: str = "answer", score: int | None = 7, *, is_retry: bool = False,
    tags: list[str] | None = None, status: str = "ok",
    input_method: str = "typed", submitted_at: datetime | None = None,
) -> InterviewAnswer:
    fields = dict(
        text=text, score=score, is_retry=is_retry, failure_tags=list(tags or []),
        critique="a critique", fix="a fix", evaluation_status=status,
        input_method=input_method,
    )
    if submitted_at is not None:
        fields["submitted_at"] = submitted_at
    return InterviewAnswer(**fields)


def _completed_session(
    session_id: str,
    questions: list[InterviewQuestion],
    *,
    view_ids: list[str] | None = None,
    preset_key: str = "view_deliver",
    mode: str = "Discussion",
    style: str = "Deliver",
    rubric_id: str = "argument-v3",
    postmortem: InterviewPostmortem | None = None,
    model: str = "test-model",
    topic: str = "Term premium",
    model_note_ids: list[str] | None = None,
) -> InterviewSession:
    return InterviewSession(
        id=session_id, mode=mode, preset_key=preset_key, rubric_id=rubric_id,
        practice_style=style, topic=topic, model=model,
        status="completed", completed_at=datetime.now(timezone.utc),
        view_ids=list(view_ids or []), model_note_ids=list(model_note_ids or []),
        postmortem=postmortem, questions=questions,
    )


def _postmortem_json(
    overall: str = "Solid overall.", strongest=None, problems=None, repeat=None,
) -> str:
    return _json({
        "overall_performance": overall,
        "strongest_areas": ["Q1: clear mechanism"] if strongest is None else strongest,
        "biggest_problems": ["knowledge: Q2 gap"] if problems is None else problems,
        "concepts_to_repeat": ["Drill X"] if repeat is None else repeat,
    })


def test_p7_final_turn_is_ordinary_and_pending() -> None:
    assert "postmortem" not in _evaluation_schema(final_turn=True), \
        "the final turn must not request a postmortem"
    session = _new_session(target_questions=1)
    provider = FakeProvider([_json({
        "score": 7, "critique": "Bottom line was late.", "fix": "Lead with the view.",
    })])
    updated, result = evaluate_answer(session.id, "My answer.", provider=provider)
    assert len(provider.calls) == 1
    assert provider.calls[0]["options"].max_tokens == EVAL_MAX_TOKENS, \
        "the final turn uses the ordinary budget"
    assert result["done"] is True
    assert updated.status == "completed"
    assert updated.postmortem is not None and updated.postmortem.status == "pending"
    print("PASS: P7 the final turn is ordinary, one call, completed with a pending summary")


def test_p8_synthesis_input_shape_and_view_diagnostic() -> None:
    view_id = "view-p8"
    _install_state_stub()
    _seed_view(view_id)
    _patch_history_file(_temp_history_file())
    long_answer = "L" * 1500
    questions = []
    for number in range(1, 15):
        answers = [_answer(text=long_answer if number == 1 else f"answer {number}", score=7)]
        if number == 7:
            answers.append(_answer(text="retry answer", score=8, is_retry=True))
        questions.append(InterviewQuestion(text=f"question {number}", answers=answers))
    session = _completed_session(
        "p8-session", questions, view_ids=[view_id],
        postmortem=InterviewPostmortem(status="pending"),
    )
    save_session(session)

    provider = FakeProvider([_postmortem_json()])
    updated = synthesize_session(session.id, provider=provider)
    assert len(provider.calls) == 1
    assert updated.postmortem.status == "ok"
    prompt = json.loads(provider.calls[0]["messages"][1]["content"])
    records = prompt["answers"]
    assert len(records) == 15, "14 first answers plus one retry"
    assert sum(1 for record in records if record["attempt"] == "retry") == 1
    first = next(record for record in records if record["question"].startswith("Q1:"))
    assert len(first["answer"]) == 1000, "a >3-question session caps answers at 1000 characters"
    assert _view_practice(view_id).latest_diagnostic, "the View diagnostic must be written"
    print("PASS: P8 15 records, retry marked, long answer capped at 1000, diagnostic written")


def test_p9_short_session_keeps_full_answer_text() -> None:
    long_answer = "S" * 1500
    questions = [
        InterviewQuestion(text="q1", answers=[_answer(text=long_answer, score=7)]),
        InterviewQuestion(text="q2", answers=[_answer(text="short", score=6)]),
    ]
    _patch_history_file(_temp_history_file())
    session = _completed_session(
        "p9-session", questions, postmortem=InterviewPostmortem(status="pending"),
    )
    save_session(session)
    provider = FakeProvider([_postmortem_json()])
    synthesize_session(session.id, provider=provider)
    prompt = json.loads(provider.calls[0]["messages"][1]["content"])
    first = prompt["answers"][0]
    assert first["answer"] == long_answer, "a <=3-question session keeps full answer text"
    assert len(first["answer"]) == 1500
    print("PASS: P9 a short session passes full answer text to synthesis")


def test_p10_synthesis_input_carries_retry_free_stats() -> None:
    questions = [
        InterviewQuestion(text="q1", answers=[
            _answer(text="a1", score=8),
            _answer(text="retry", score=2, is_retry=True, status="partial"),
        ]),
        InterviewQuestion(text="q2", answers=[_answer(text="a2", score=6)]),
    ]
    _patch_history_file(_temp_history_file())
    session = _completed_session(
        "p10-session", questions, postmortem=InterviewPostmortem(status="pending"),
    )
    save_session(session)
    stats = session_stats(session)
    assert stats["first_attempt_count"] == 2
    assert stats["evaluated_count"] == 2
    assert stats["mean_first_attempt_score"] == 7.0, "retries must be excluded"
    provider = FakeProvider([_postmortem_json()])
    synthesize_session(session.id, provider=provider)
    sent = json.loads(provider.calls[0]["messages"][1]["content"])["session_stats"]
    assert sent["answers_first_attempt"] == 2
    assert sent["answers_evaluated"] == 2
    assert sent["mean_first_attempt_score"] == 7.0, "input stats must exclude the retry"
    print("PASS: P10 synthesis input carries retry-free session_stats numbers")


def test_p11_synthesis_repair_and_output_failure() -> None:
    _patch_history_file(_temp_history_file())
    session = _completed_session(
        "p11-a", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        postmortem=InterviewPostmortem(status="pending"),
    )
    save_session(session)
    provider = FakeProvider(["not valid json", _postmortem_json()])
    updated = synthesize_session(session.id, provider=provider)
    assert len(provider.calls) == 2
    assert provider.calls[0]["options"].max_tokens == SYNTHESIS_MAX_TOKENS
    assert provider.calls[1]["options"].max_tokens == int(SYNTHESIS_MAX_TOKENS * 1.5)
    assert updated.postmortem.status == "ok"
    assert updated.postmortem.synthesis_error == ""

    session_b = _completed_session(
        "p11-b", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        postmortem=InterviewPostmortem(status="pending"),
    )
    save_session(session_b)
    provider_b = FakeProvider(["not json", "still not json"])
    updated_b = synthesize_session(session_b.id, provider=provider_b)
    assert len(provider_b.calls) == 2
    assert updated_b.postmortem.status == "missing"
    assert updated_b.postmortem.synthesis_error == "output"
    print("PASS: P11 malformed-then-valid repairs to ok; malformed twice records an output failure")


def test_p12_provider_failure_never_downgrades_or_double_counts() -> None:
    view_id = "view-p12"
    _install_state_stub()
    _seed_view(view_id)
    _patch_history_file(_temp_history_file())
    session = start_session(
        mode="Discussion", topic="Term premium", preset_key="view_deliver",
        target_questions=1, view_ids=[view_id], practice_style="Deliver",
    )
    evaluation = FakeProvider([_json({"score": 7, "critique": "c", "fix": "f"})])
    completed, result = evaluate_answer(session.id, "My answer.", provider=evaluation)
    assert result["done"] is True
    practice = _view_practice(view_id)
    assert practice.practice_count == 1 and practice.delivery_attempts == 1
    assert practice.latest_diagnostic == []

    failing = ProviderFailureProvider()
    updated = synthesize_session(session.id, provider=failing)
    assert failing.calls == 1
    assert updated.postmortem.status == "missing"
    assert updated.postmortem.synthesis_error == "provider"
    practice = _view_practice(view_id)
    assert practice.practice_count == 1, "synthesis must not bump counts again"
    assert practice.delivery_attempts == 1
    assert practice.latest_diagnostic == [], "a failed synthesis must not touch the diagnostic"
    print("PASS: P12 provider failure records 'provider', bumps counts once, leaves diagnostics")


def test_p13_ok_is_not_rebilled_and_partial_is_never_downgraded() -> None:
    _patch_history_file(_temp_history_file())
    ok_session = _completed_session(
        "p13-ok", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        postmortem=InterviewPostmortem(
            overall_performance="Good.", biggest_problems=["p"],
            strongest_areas=["s"], concepts_to_repeat=["c"], status="ok",
        ),
    )
    save_session(ok_session)
    provider = FakeProvider([])
    returned = synthesize_session(ok_session.id, provider=provider)
    assert len(provider.calls) == 0, "an existing ok summary must not be re-billed"
    assert returned.postmortem.status == "ok"

    partial_session = _completed_session(
        "p13-partial", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        postmortem=InterviewPostmortem(
            overall_performance="Partial.", biggest_problems=["p"],
            strongest_areas=[], concepts_to_repeat=[], status="partial",
        ),
    )
    save_session(partial_session)
    provider_b = FakeProvider(["not json", "still not json"])
    returned_b = synthesize_session(partial_session.id, provider=provider_b)
    assert returned_b.postmortem.status == "partial", "a worse retry must not downgrade"
    assert returned_b.postmortem.overall_performance == "Partial."
    print("PASS: P13 ok summaries are not re-billed and partial summaries are never downgraded")


def test_p14_phase1_missing_summary_is_upgraded() -> None:
    _patch_history_file(_temp_history_file())
    session = _completed_session(
        "p14-session",
        [InterviewQuestion(text="q", answers=[_answer(text="my answer", score=7, tags=["RAMBLE"])])],
        postmortem=InterviewPostmortem(status="missing"),
    )
    session.prompt_pack_version = LEGACY_V2_PROMPT_PACK
    save_session(session)
    provider = FakeProvider([_postmortem_json()])
    updated = synthesize_session(session.id, provider=provider)
    assert len(provider.calls) == 1
    assert updated.postmortem.status == "ok"
    print("PASS: P14 a Phase 1 session's missing summary is upgraded to ok")


def test_pfix_empty_content_uses_repair_and_records_output() -> None:
    # Empty content must behave like malformed output: one repair, then a
    # recorded output failure, never a raised exception.
    _patch_history_file(_temp_history_file())
    session = _completed_session(
        "pfix-empty", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        postmortem=InterviewPostmortem(status="pending"),
    )
    save_session(session)
    provider = FakeProvider([InterviewOutputError("empty content"), _postmortem_json()])
    updated = synthesize_session(session.id, provider=provider)
    assert len(provider.calls) == 2, "empty content must still use the one repair"
    assert provider.calls[1]["options"].max_tokens == int(SYNTHESIS_MAX_TOKENS * 1.5)
    assert updated.postmortem.status == "ok"

    session_b = _completed_session(
        "pfix-empty-2", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        postmortem=InterviewPostmortem(status="pending"),
    )
    save_session(session_b)
    provider_b = FakeProvider([
        InterviewOutputError("empty content"), InterviewOutputError("empty content"),
    ])
    updated_b = synthesize_session(session_b.id, provider=provider_b)
    assert len(provider_b.calls) == 2
    assert updated_b.postmortem.status == "missing"
    assert updated_b.postmortem.synthesis_error == "output"
    print("PASS: empty synthesis content repairs to ok, or twice records an output failure")


def test_pfix_older_session_retry_keeps_latest_diagnostic() -> None:
    view_id = "view-pfix"
    _install_state_stub()
    _seed_view(view_id)
    _patch_history_file(_temp_history_file())
    older = _completed_session(
        "pfix-older", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        view_ids=[view_id], postmortem=InterviewPostmortem(status="missing"),
    )
    older.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = _completed_session(
        "pfix-newer", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        view_ids=[view_id], postmortem=InterviewPostmortem(status="missing"),
    )
    newer.completed_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    save_session(older)
    save_session(newer)

    synthesize_session("pfix-newer", provider=FakeProvider([
        _postmortem_json(problems=["knowledge: newer"], strongest=["Q1: newer"]),
    ]))
    assert _view_practice(view_id).latest_diagnostic == ["knowledge: newer", "Q1: newer"]

    synthesize_session("pfix-older", provider=FakeProvider([
        _postmortem_json(problems=["knowledge: older"], strongest=["Q1: older"]),
    ]))
    assert _view_practice(view_id).latest_diagnostic == ["knowledge: newer", "Q1: newer"], \
        "an older session's retried summary must not overwrite the newest diagnostic"
    print("PASS: retrying an older session keeps the View's latest diagnostic")


def test_p21_reference_answer_carries_context_and_caches() -> None:
    _patch_history_file(_temp_history_file())
    session = _completed_session(
        "p21-session",
        [InterviewQuestion(
            text="Walk me through your rates trade.",
            answers=[_answer(text="My delivery.")],
        )],
        preset_key="job_interview", mode="Simulation", style="",
        rubric_id="interview-v3", topic="Rates interview",
    )
    session.materials = "ROLE: rates PM. RESUME: ..."
    save_session(session)

    provider = FakeProvider([
        "A strong answer.\n\nWhat the strong version does differently\n- Bottom line first.",
    ])
    text = reference_answer(session.id, provider=provider)
    assert len(provider.calls) == 1
    prompt = json.loads(provider.calls[0]["messages"][1]["content"])
    assert prompt["question"] == "Walk me through your rates trade.", \
        "the reference call must be grounded in the actual question"
    assert prompt["materials"] == "ROLE: rates PM. RESUME: ...", \
        "Job Interview materials must reach the reference call"
    assert prompt["candidate_answer"] == "My delivery."
    assert prompt["target_rubric"] == RUBRICS["interview"][1], \
        "a Job Interview session references its own rubric family"

    cached = reference_answer(session.id, provider=FakeProvider([]))
    assert cached == text, "a cached reference answer must never re-bill the extra call"
    print("PASS: P21 reference answer carries question and materials, and re-renders without re-billing")


def test_v1_currency_note_sits_in_the_response_contract() -> None:
    from services.interview_prompts import (
        BASE_INTERVIEWER_PROMPT, EVALUATION_PRIVACY_NOTE, TRANSCRIPT_NOTE,
        compose_runtime_prompt, view_currency_note,
    )
    note = view_currency_note("2026-11-20")
    assert "2026-11-20" in note and "may be out of date" in note
    prompt = compose_runtime_prompt(
        preset_key="view_deliver", mode="Discussion", view_note=note, transcript_note=True,
    )
    contract = prompt.index("# RESPONSE CONTRACT")
    assert contract < prompt.index(EVALUATION_PRIVACY_NOTE) < prompt.index(note) \
        < prompt.index(TRANSCRIPT_NOTE), \
        "the note belongs in the response contract, after privacy and before the transcript note"
    plain = compose_runtime_prompt(preset_key="view_deliver", mode="Discussion")
    assert "may be out of date" not in plain, "no note unless a View is attached"
    assert BASE_INTERVIEWER_PROMPT in prompt, "the base interviewer prompt must stay intact"
    assert "out of date" not in BASE_INTERVIEWER_PROMPT
    print("PASS: V1 the stale-card note sits in the response contract, only when supplied")


def test_v2_session_prompts_carry_the_note_only_for_view_sessions() -> None:
    real_today = controller._today
    controller._today = lambda: "2026-11-20"
    try:
        view_session = _new_session(
            mode="Discussion", preset_key="view_deliver", target_questions=1,
            view_context='{"topic": "Term premium"}',
        )
        system = controller._system(view_session, "state")
        assert "Today's date is 2026-11-20" in system
        assert "may be out of date" in system

        drill = _new_session()
        assert "may be out of date" not in controller._system(drill, "state"), \
            "a Quant Drill session has no stored View and must not get the note"

        view_completed = _completed_session(
            "v2-view", [InterviewQuestion(text="Q?", answers=[_answer()])],
        )
        view_completed.view_context = '{"topic": "Term premium"}'
        setup = controller._synthesis_prompt(view_completed)["setup"]
        assert "2026-11-20" in setup["view_currency_note"]

        plain_completed = _completed_session(
            "v2-plain", [InterviewQuestion(text="Q?", answers=[_answer()])],
            preset_key="quant_drill", mode="Drill", style="", rubric_id="technical-v3",
        )
        assert "view_currency_note" not in controller._synthesis_prompt(plain_completed)["setup"]

        _patch_history_file(_temp_history_file())
        save_session(view_completed)
        provider = FakeProvider(["A strong answer."])
        reference_answer(view_completed.id, provider=provider)
        prompt = json.loads(provider.calls[0]["messages"][1]["content"])
        assert "2026-11-20" in prompt["view_currency_note"]
        assert "correct developments" in provider.calls[0]["messages"][0]["content"]
    finally:
        controller._today = real_today
    print("PASS: V2 the note reaches grading, synthesis, and reference answers for View sessions only")


def test_v3_view_context_exposes_its_age() -> None:
    from datetime import timedelta
    from services.topic_views import view_context

    updated = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
    view = TopicView(id="v3", name="Term premium", bottom_line="Up.", updated_at=updated)
    data = json.loads(view_context(view))
    assert list(data)[-1] == "last_updated", "last_updated must stay the final key"
    assert data["last_updated"] == "2026-03-02"
    assert "out of date" in data["instruction"]

    view.reviewed_at = updated + timedelta(days=40)
    assert json.loads(view_context(view))["last_updated"] == "2026-04-11", \
        "Still holds counts as the latest confirmation"

    view.reviewed_at = (updated + timedelta(days=40)).replace(tzinfo=None)
    assert json.loads(view_context(view))["last_updated"] == "2026-04-11", \
        "a naive reviewed_at must not break the comparison"
    print("PASS: V3 view_context reports when the View was last edited or confirmed")


def _fc_claim(**overrides) -> dict:
    claim = {
        "claim": "Core PCE was 2.9% in September.", "origin": "answer",
        "status": "outdated", "latest_value": "2.7%", "reference_period": "Oct 2026",
        "released": "2026-11-26", "source_url": "https://www.bea.gov/news/2026/pce",
        "source_title": "BEA PCE", "note": "Revised down.",
    }
    claim.update(overrides)
    return claim


class FakeWeb:
    """Stands in for fact_check._web_complete: (messages, model) -> (text, cited URLs)."""

    def __init__(self, claims=None, cited=("https://bea.gov/news/2026/pce",), *, text=None,
                 error=None, hook=None):
        self.text = text if text is not None else _json({"claims": claims or []})
        self.cited = set(cited)
        self.error = error
        self.hook = hook
        self.calls: list[tuple] = []

    def __call__(self, messages, model):
        self.calls.append((messages, model))
        if self.hook:
            self.hook()
        if self.error:
            raise self.error
        return self.text, set(self.cited)


def _fc_session(session_id: str = "fc-session", *, text: str = "Core PCE was 2.9% in September.",
                voice: bool = False, view_context: str = "") -> InterviewSession:
    _patch_history_file(_temp_history_file())
    answer = _answer(text=text)
    answer.voice = voice
    session = _completed_session(
        session_id,
        [InterviewQuestion(text="What's your view on Inflation?", answers=[answer])],
        topic="Inflation",
    )
    session.view_context = view_context
    save_session(session)
    return session


def test_f1_claims_are_citation_gated() -> None:
    from services.fact_check import MAX_CLAIMS, validate_claims

    cited = {"http://bea.gov/news/2026/pce/?utm_source=x"}
    claims = validate_claims({"claims": [
        _fc_claim(origin="card", claim="Card fact."),
        _fc_claim(),
        _fc_claim(claim="Unemployment is 4.1%.", status="current",
                  source_url="https://bls.gov/news.release/empsit.htm", latest_value="4.1%"),
        _fc_claim(claim="Payrolls rose 200k.", status="wrong", source_url=""),
        _fc_claim(claim="GDP grew 2%.", status="Up-to-date"),
        _fc_claim(claim="Maybe so.", status="maybe"),
        _fc_claim(claim="   "),
        "not a claim",
    ]}, cited)
    by_claim = {c.claim: c for c in claims}
    assert "   " not in by_claim and len(claims) == 6, "blank and non-dict entries are skipped"

    sourced = by_claim["Core PCE was 2.9% in September."]
    assert sourced.status == "outdated" and sourced.latest_value == "2.7%", \
        "a cited source survives scheme, www, query and trailing-slash differences"
    assert sourced.source_url == "https://www.bea.gov/news/2026/pce"

    uncited = by_claim["Unemployment is 4.1%."]
    assert uncited.status == "unverifiable" and "No cited source" in uncited.note
    assert uncited.source_url == "" and uncited.latest_value == "" and uncited.released == "", \
        "an unsourced figure must not be shown"
    assert by_claim["Payrolls rose 200k."].status == "unverifiable", "no URL means no verdict"
    assert by_claim["GDP grew 2%."].status == "current", "status aliases are normalised"
    assert by_claim["Maybe so."].status == "unverifiable"
    assert claims[-1].origin == "card", "answer claims come before card facts"

    many = validate_claims({"claims": [_fc_claim(claim=f"Claim {i}.") for i in range(9)]}, cited)
    assert len(many) == MAX_CLAIMS == 6
    for bad in ({}, {"claims": "none"}, [], None):
        try:
            validate_claims(bad, cited)
        except ValueError:
            continue
        raise AssertionError("a response without a claims list must be an output failure")
    print("PASS: F1 statuses need a cited source, aliases normalise, the list clamps to 6")


def test_f2_result_is_cached_and_no_citations_is_retryable() -> None:
    session = _fc_session()
    web = FakeWeb([_fc_claim()])
    result = fact_check_session(session.id, web_complete=web)
    assert result.fact_check.status == "ok" and result.fact_check.error == ""
    assert result.fact_check.claims[0].status == "outdated"
    assert result.fact_check.model, "the model that ran is recorded"
    again = fact_check_session(session.id, web_complete=FakeWeb([]))
    assert len(web.calls) == 1 and again.fact_check.claims[0].claim == result.fact_check.claims[0].claim, \
        "a cached usable result must not call the model again"

    uncited = _fc_session("fc-uncited")
    web = FakeWeb([_fc_claim(status="current")], cited=())
    stored = fact_check_session(uncited.id, web_complete=web).fact_check
    assert stored.status == "ok" and stored.error == "no_citations"
    assert all(c.status == "unverifiable" for c in stored.claims)
    retry = FakeWeb([_fc_claim()])
    fact_check_session(uncited.id, web_complete=retry)
    assert len(retry.calls) == 1, "a no-citations result is stored but can be retried"
    assert load_database().sessions[0].fact_check.error == "", "the retry replaced it"
    print("PASS: F2 usable results are cached; a no-citations result can be retried")


def test_f3_failures_record_missing_and_never_raise() -> None:
    session = _fc_session()
    stored = fact_check_session(
        session.id, web_complete=FakeWeb(error=InterviewProviderError("boom")),
    ).fact_check
    assert (stored.status, stored.error) == ("missing", "provider")
    for web in (
        FakeWeb(error=InterviewOutputError("empty")),
        FakeWeb(text="plain prose, no json"),
        FakeWeb(text=_json({"claims": "oops"})),
    ):
        stored = fact_check_session(session.id, web_complete=web).fact_check
        assert (stored.status, stored.error) == ("missing", "output")
    fixed = fact_check_session(session.id, web_complete=FakeWeb([_fc_claim()])).fact_check
    assert fixed.status == "ok", "a failed check is retried on the next click"

    active = _new_session(mode="Discussion", preset_key="view_deliver", target_questions=2)
    for target in (active.id, "missing-session"):
        try:
            fact_check_session(target, web_complete=FakeWeb([]))
        except RuntimeError:
            continue
        raise AssertionError("only a completed session can be fact-checked")
    print("PASS: F3 provider and output failures record 'missing'; non-completed sessions raise")


def test_f4_prompt_carries_card_facts_and_dictation_flag() -> None:
    from models.schema import ViewFact, ViewPoint
    from services.topic_views import view_context

    view = TopicView(id="fc-view", name="Inflation", points=[ViewPoint(
        title="Disinflation stalled",
        facts=[ViewFact(text="Core PCE 2.9% y/y", as_of="2026-09-30", source="BEA"),
               ViewFact(text="   ")],
    )])
    session = _fc_session("fc-card", voice=True, view_context=view_context(view))
    web = FakeWeb([_fc_claim(origin="card", claim="Core PCE 2.9% y/y")])
    fact_check_session(session.id, web_complete=web)
    messages, model = web.calls[0]
    prompt = json.loads(messages[1]["content"])
    assert prompt["answer_was_dictated"] is True
    assert prompt["candidate_answer"] == "Core PCE was 2.9% in September."
    assert prompt["card_facts"] == [{
        "point": "Disinflation stalled", "fact": "Core PCE 2.9% y/y",
        "as_of": "2026-09-30", "source": "BEA",
    }], "only real dated card facts are sent"
    assert prompt["today"] and "misheard" in messages[0]["content"]

    from services.fact_check import check_claims
    nothing = FakeWeb([])
    empty = check_claims(topic="x", answer_text="  ", card_facts=[], voice=False,
                         model="m", today="2026-11-20", web_complete=nothing)
    assert empty.status == "ok" and empty.claims == [] and not nothing.calls, \
        "no answer and no card facts means nothing to check, so no paid call"
    print("PASS: F4 card facts and the dictation flag reach the prompt; empty input makes no call")


def test_f5_old_history_loads_without_fact_check() -> None:
    history = _temp_history_file()
    _patch_history_file(history)
    history.write_text(json.dumps(_legacy_payload()), encoding="utf-8")
    sessions = load_database().sessions
    assert sessions and sessions[0].fact_check is None
    print("PASS: F5 a saved session without fact_check loads unchanged")


def test_f6_background_writes_do_not_erase_each_other() -> None:
    from models.interview import FactCheck
    from storage.interview_store import get_session, update_session

    # The hazard itself: saving a stale copy erases a field written meanwhile.
    session = _fc_session("fc-race-0")
    stale = get_session(session.id)
    update_session(session.id, lambda s: setattr(s, "reference_answer", "written meanwhile"))
    save_session(stale)
    assert get_session(session.id).reference_answer == "", "a stale save really does lose data"

    # Summary call in flight while a reference answer and a fact check are stored.
    session = _fc_session("fc-race-1")
    session.postmortem = InterviewPostmortem(status="pending")
    save_session(session)

    class Racing(FakeProvider):
        def complete(self, messages, options):
            def write(fresh):
                fresh.reference_answer = "A strong answer."
                fresh.fact_check = FactCheck(status="ok", model="m")
            update_session(session.id, write)
            return super().complete(messages, options)

    synthesize_session(session.id, provider=Racing([_postmortem_json()]))
    stored = get_session(session.id)
    assert stored.postmortem.status == "ok", "the summary is saved"
    assert stored.reference_answer == "A strong answer." and stored.fact_check is not None, \
        "the summary must not erase fields written while it was running"

    # Reference answer call in flight while the summary and a fact check are stored.
    session = _fc_session("fc-race-2")

    class Racing2(FakeProvider):
        def complete(self, messages, options):
            def write(fresh):
                fresh.postmortem = InterviewPostmortem(status="ok", overall_performance="Fine.")
                fresh.fact_check = FactCheck(status="ok", model="m")
            update_session(session.id, write)
            return super().complete(messages, options)

    text = reference_answer(session.id, provider=Racing2(["A strong answer."]))
    stored = get_session(session.id)
    assert text == "A strong answer." and stored.reference_answer == text
    assert stored.postmortem.status == "ok" and stored.fact_check is not None, \
        "a reference answer must not erase the summary or fact check"

    # A fact check completing while a summary is stored keeps the summary.
    session = _fc_session("fc-race-3")
    update_session(session.id, lambda s: setattr(
        s, "postmortem", InterviewPostmortem(status="ok", overall_performance="Fine.")))

    def store_reference() -> None:
        update_session(session.id, lambda s: setattr(s, "reference_answer", "kept"))

    fact_check_session(session.id, web_complete=FakeWeb([_fc_claim()], hook=store_reference))
    stored = get_session(session.id)
    assert stored.fact_check.status == "ok" and stored.reference_answer == "kept" \
        and stored.postmortem.status == "ok"
    print("PASS: F6 summary, reference answer and fact check never erase each other")


def test_f7_web_request_shape_retry_and_citations() -> None:
    import copy
    import types

    import config as app_config
    import openai
    from services import fact_check as fc

    class StatusError(Exception):
        def __init__(self, status: int):
            super().__init__(f"status {status}")
            self.status_code = status

    def resp(content, annotations=None, extra=None, with_attr=True):
        fields = {"content": content}
        if with_attr:
            fields["annotations"] = annotations
        if extra is not None:
            fields["model_extra"] = extra
        message = types.SimpleNamespace(**fields)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    def install(script):
        calls = []

        class Completions:
            def create(self, **kwargs):
                calls.append(copy.deepcopy(kwargs))
                item = script.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        class Chat:
            completions = Completions()

        class Client:
            def __init__(self, **kwargs):
                self.chat = Chat()

        openai.OpenAI = Client
        return calls

    real_client, real_key = openai.OpenAI, fc.user_settings.llm_api_key
    fc.user_settings.llm_api_key = lambda provider="": "test-key"
    messages = [{"role": "user", "content": "x"}]
    try:
        dict_form = {"type": "url_citation", "url_citation": {"url": "https://a.gov/x"}}
        object_form = types.SimpleNamespace(
            type="url_citation", url_citation=types.SimpleNamespace(url="https://b.gov/y"),
        )
        calls = install([resp("{}", [dict_form, object_form, {"type": "other"}])])
        text, cited = fc._web_complete(messages, "some/model")
        assert text == "{}" and cited == {"https://a.gov/x", "https://b.gov/y"}, \
            "citations are read from dict and object annotations, ignoring other types"
        request = calls[0]
        assert request["model"] == "some/model"
        assert request["max_tokens"] == app_config.FACT_CHECK_MAX_TOKENS
        assert "temperature" not in request and "response_format" not in request, \
            "search models may reject temperature, and JSON mode can break tool turns"
        body = request["extra_body"]
        assert body["reasoning"] == {"effort": "minimal"}, \
            "reasoning is minimised, not disabled: GLM 5.3 refuses to disable it"
        assert body["tools"] == [{
            "type": "openrouter:web_search",
            "parameters": {
                "max_results": app_config.FACT_CHECK_MAX_RESULTS,
                "max_uses": app_config.FACT_CHECK_MAX_SEARCHES,
            },
        }]

        install([resp("{}", with_attr=False, extra={"annotations": [dict_form]})])
        assert fc._web_complete(messages, "m")[1] == {"https://a.gov/x"}, \
            "annotations the SDK leaves in model_extra are still read"

        calls = install([StatusError(400), resp("ok")])
        assert fc._web_complete(messages, "m")[0] == "ok"
        assert len(calls) == 2 and "reasoning" not in calls[1]["extra_body"], \
            "a 400 is retried once without the reasoning hint"
        assert calls[1]["extra_body"]["tools"], "the retry keeps the search tool"

        calls = install([StatusError(401), resp("never")])
        try:
            fc._web_complete(messages, "m")
        except InterviewProviderError:
            pass
        else:
            raise AssertionError("an auth failure must surface as a provider error")
        assert len(calls) == 1, "an auth failure is never sent twice"

        calls = install([StatusError(400), StatusError(400)])
        try:
            fc._web_complete(messages, "m")
        except InterviewProviderError:
            pass
        else:
            raise AssertionError("two 400s must surface as a provider error")
        assert len(calls) == 2

        install([resp("   ")])
        try:
            fc._web_complete(messages, "m")
        except InterviewOutputError:
            pass
        else:
            raise AssertionError("empty content is an output failure")
        install([types.SimpleNamespace(choices=[])])
        try:
            fc._web_complete(messages, "m")
        except InterviewProviderError:
            pass
        else:
            raise AssertionError("no choices is a provider failure")

        calls = install([resp("never")])
        fc.user_settings.llm_api_key = lambda provider="": ""
        try:
            fc._web_complete(messages, "m")
        except InterviewProviderError:
            pass
        else:
            raise AssertionError("no OpenRouter key must fail before any request")
        assert calls == []
    finally:
        openai.OpenAI, fc.user_settings.llm_api_key = real_client, real_key
    print("PASS: F7 the web call uses minimal reasoning and the search tool, retries only a 400, reads citations")


# ---------------------------------------------------------------------------
# Phase 2 batch C (Task 4): trends compare like with like.
# ---------------------------------------------------------------------------


def test_p15_view_stats_use_current_key_only() -> None:
    view_id = "view-p15"
    _patch_history_file(_temp_history_file())
    sessions = []
    for index in range(2):
        session = _completed_session(
            f"p15-legacy-{index}",
            [InterviewQuestion(text="q", answers=[_answer(score=4 + index)])],
            view_ids=[view_id], rubric_id="shared-v2",
        )
        session.completed_at = datetime(2026, 1, 1 + index, tzinfo=timezone.utc)
        sessions.append(session)
    for index in range(3):
        session = _completed_session(
            f"p15-v3-{index}",
            [InterviewQuestion(text="q", answers=[_answer(score=6 + index)])],
            view_ids=[view_id], rubric_id="argument-v3",
        )
        session.completed_at = datetime(2026, 2, 1 + index, tzinfo=timezone.utc)
        sessions.append(session)
    for session in sessions:
        save_session(session)
    stats = view_practice_stats()[view_id]
    assert stats["other_key_sessions"] == 2
    assert stats["current_key_sessions"] == 3
    assert len(stats["series"]) == 3, "only the three v3 sessions form the series"
    assert stats["latest"]["score"] == 8.0
    print("PASS: P15 View stats use the current key only; 2 older sessions are counted separately")


def test_p16_model_change_starts_a_new_series() -> None:
    view_id = "view-p16"
    _patch_history_file(_temp_history_file())
    older = _completed_session(
        "p16-a", [InterviewQuestion(text="q", answers=[_answer(score=9)])],
        view_ids=[view_id], model="model-a",
    )
    older.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = _completed_session(
        "p16-b", [InterviewQuestion(text="q", answers=[_answer(score=5)])],
        view_ids=[view_id], model="model-b",
    )
    newer.completed_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    save_session(older)
    save_session(newer)
    stats = view_practice_stats()[view_id]
    assert stats["current_key_sessions"] == 1
    assert stats["other_key_sessions"] == 1
    assert stats["latest"]["score"] == 5.0, "the latest session's model defines the series"
    assert len(stats["series"]) == 1
    print("PASS: P16 a model change starts a new View series")


def test_p17_preset_change_starts_a_new_series() -> None:
    view_id = "view-p17"
    _patch_history_file(_temp_history_file())
    deliver = _completed_session(
        "p17-d", [InterviewQuestion(text="q", answers=[_answer(score=9)])],
        view_ids=[view_id], preset_key="view_deliver", style="Deliver",
    )
    deliver.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    discuss = _completed_session(
        "p17-c", [InterviewQuestion(text="q", answers=[_answer(score=5)])],
        view_ids=[view_id], preset_key="view_discuss", style="Discuss",
    )
    discuss.completed_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    save_session(deliver)
    save_session(discuss)
    stats = view_practice_stats()[view_id]
    assert stats["current_key_sessions"] == 1
    assert stats["other_key_sessions"] == 1
    print("PASS: P17 Deliver and Discuss sessions form separate View series")


def test_p18_custom_and_unanchored_are_excluded() -> None:
    view_id = "view-p18"
    _patch_history_file(_temp_history_file())
    save_preferred_model("test-model")
    custom = _completed_session(
        "p18-custom", [InterviewQuestion(text="q", answers=[_answer(score=10)])],
        view_ids=[view_id], rubric_id="custom", model_note_ids=["note-p18"],
    )
    custom.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    unanchored = _completed_session(
        "p18-unanchored", [InterviewQuestion(text="q", answers=[_answer(score=10)])],
        view_ids=[view_id], rubric_id="unanchored", model_note_ids=["note-p18"],
    )
    unanchored.completed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    save_session(custom)
    save_session(unanchored)
    assert view_practice_stats().get(view_id) is None, "custom/unanchored must not form a series"
    summary = performance_summary()
    assert summary["strong_topics"] == []
    assert "Term premium" not in summary["improving"]
    model_stats = model_practice_stats()
    assert model_stats["note-p18"]["by_style"]["Deliver"]["avg_score"] is None
    print("PASS: P18 custom and unanchored sessions are absent from every score number")


def test_p19_retries_excluded_partials_included() -> None:
    view_id = "view-p19"
    _patch_history_file(_temp_history_file())
    save_preferred_model("test-model")
    session = _completed_session(
        "p19-session",
        [InterviewQuestion(text="q", answers=[
            _answer(score=8, status="ok"),
            _answer(score=6, status="partial"),
            _answer(score=2, is_retry=True, status="partial"),
        ])],
        view_ids=[view_id], rubric_id="argument-v3", model_note_ids=["note-p19"],
    )
    save_session(session)
    stats = view_practice_stats()[view_id]
    assert stats["series"][-1]["score"] == 7.0, "retry excluded, partial included"
    assert performance_summary()["strong_topics"] == ["Term premium"], "mean of 8 and 6 is 7"
    assert model_practice_stats()["note-p19"]["by_style"]["Deliver"]["avg_score"] == 7.0
    print("PASS: P19 retries are excluded from averages and partial answers are included")


def test_p20_improving_uses_only_the_current_key() -> None:
    _patch_history_file(_temp_history_file())
    save_preferred_model("test-model")
    questions = []
    for index, score in enumerate([4, 5, 6, 7]):
        questions.append(InterviewQuestion(text=f"typed {index}", answers=[
            _answer(
                score=score, input_method="typed",
                submitted_at=datetime(2026, 1, 1 + index, tzinfo=timezone.utc),
            ),
        ]))
    for index, score in enumerate([8, 7, 6, 5]):
        questions.append(InterviewQuestion(text=f"voice {index}", answers=[
            _answer(
                score=score, input_method="voice",
                submitted_at=datetime(2026, 2, 1 + index, tzinfo=timezone.utc),
            ),
        ]))
    save_session(_completed_session("p20-session", questions, rubric_id="argument-v3"))
    summary = performance_summary()
    # Combined [4,5,6,7] then [8,7,6,5] would read as improving; the current key
    # (voice) is falling, so the topic must not be flagged.
    assert "Term premium" not in summary["improving"], \
        "the improving flag must reflect only the current comparability key"
    print("PASS: P20 the improving flag reflects only the current comparability key")


def test_pfix_movement_gates_global_and_per_view() -> None:
    # Global gate: 10 trend-eligible *-v3 sessions app-wide enable movement;
    # shared-v2 and custom sessions never count toward the global gate.
    _patch_history_file(_temp_history_file())
    for index in range(9):
        save_session(_completed_session(
            f"mv-global-{index}",
            [InterviewQuestion(text="q", answers=[_answer(score=6)])],
            rubric_id="argument-v3",
        ))
    save_session(_completed_session(
        "mv-shared", [InterviewQuestion(text="q", answers=[_answer(score=6)])],
        rubric_id="shared-v2",
    ))
    save_session(_completed_session(
        "mv-custom", [InterviewQuestion(text="q", answers=[_answer(score=6)])],
        rubric_id="custom",
    ))
    assert trend_session_count() == 9, "only the v3 sessions count globally"
    save_session(_completed_session(
        "mv-global-9", [InterviewQuestion(text="q", answers=[_answer(score=6)])],
        rubric_id="argument-v3",
    ))
    assert trend_session_count() == 10, "the global gate opens at ten v3 sessions"

    # Per-View gate: a delta needs two eligible sessions under the View's key.
    view_id = "view-mv"
    first = _completed_session(
        "mv-view-1", [InterviewQuestion(text="q", answers=[_answer(score=5)])],
        view_ids=[view_id], rubric_id="argument-v3",
    )
    first.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_session(first)
    assert view_practice_stats()[view_id]["current_key_sessions"] == 1, "one session is not a baseline"
    second = _completed_session(
        "mv-view-2", [InterviewQuestion(text="q", answers=[_answer(score=7)])],
        view_ids=[view_id], rubric_id="argument-v3",
    )
    second.completed_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    save_session(second)
    stats = view_practice_stats()[view_id]
    assert stats["current_key_sessions"] == 2, "two sessions under the key enable a delta"
    assert stats["delta_vs_prev"] == 2.0
    print("PASS: movement needs 10 v3 sessions app-wide and 2 under the View's key")


def main() -> None:
    print("Validating interview practice persistence and evaluation...\n")
    _install_controller_stubs()
    test_unreadable_history_is_backed_up_not_wiped()
    test_undecodable_history_is_backed_up()
    test_missing_history_returns_empty_and_first_save_creates_file()
    test_legacy_history_loads_without_error()
    test_incomplete_evaluation_twice_raises_and_saves_nothing()
    test_valid_evaluation_saves_ok_in_one_call()
    test_empty_critique_triggers_one_repair_with_1_5x_budget()
    test_empty_critique_twice_saves_partial()
    test_unusable_repair_keeps_the_first_partial_and_its_question()
    test_repair_empty_response_keeps_first_valid_score()
    test_recovery_empty_response_falls_back_to_follow_up()
    test_provider_failure_during_repair_aborts_the_turn()
    test_malformed_then_valid_without_question_uses_fallback()
    test_model_done_flag_cannot_end_a_session_early()
    test_rank_picks_the_higher_ranked_evaluation()
    test_turn_schema_requires_fix_and_drops_empty_outside_drill()
    test_sdk_failure_is_wrapped_as_provider_error()
    test_provider_failure_surfaces_and_saves_nothing()
    test_session_band_excludes_retries_and_hides_when_missing()
    test_mark_review_never_receives_a_missing_score()
    test_p1_legacy_rubric_ids_and_history_untouched()
    test_p2_input_method_derives_and_records()
    test_p3_trend_eligible_rejects_incomparable_answers()
    test_p4_presets_have_a_family_and_family_rubric()
    test_p5_start_session_stores_family_rubric_id()
    test_p6_band_gate_keeps_phase1_and_hides_incomparable()
    test_p7_final_turn_is_ordinary_and_pending()
    test_p8_synthesis_input_shape_and_view_diagnostic()
    test_p9_short_session_keeps_full_answer_text()
    test_p10_synthesis_input_carries_retry_free_stats()
    test_p11_synthesis_repair_and_output_failure()
    test_p12_provider_failure_never_downgrades_or_double_counts()
    test_p13_ok_is_not_rebilled_and_partial_is_never_downgraded()
    test_p14_phase1_missing_summary_is_upgraded()
    test_pfix_empty_content_uses_repair_and_records_output()
    test_pfix_older_session_retry_keeps_latest_diagnostic()
    test_p21_reference_answer_carries_context_and_caches()
    test_v1_currency_note_sits_in_the_response_contract()
    test_v2_session_prompts_carry_the_note_only_for_view_sessions()
    test_v3_view_context_exposes_its_age()
    test_f1_claims_are_citation_gated()
    test_f2_result_is_cached_and_no_citations_is_retryable()
    test_f3_failures_record_missing_and_never_raise()
    test_f4_prompt_carries_card_facts_and_dictation_flag()
    test_f5_old_history_loads_without_fact_check()
    test_f6_background_writes_do_not_erase_each_other()
    test_f7_web_request_shape_retry_and_citations()
    test_p15_view_stats_use_current_key_only()
    test_p16_model_change_starts_a_new_series()
    test_p17_preset_change_starts_a_new_series()
    test_p18_custom_and_unanchored_are_excluded()
    test_p19_retries_excluded_partials_included()
    test_p20_improving_uses_only_the_current_key()
    test_pfix_movement_gates_global_and_per_view()
    print("\nAll validation scenarios passed.")


if __name__ == "__main__":
    main()
