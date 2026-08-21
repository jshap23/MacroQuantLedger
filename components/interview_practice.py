"""Active interview practice UI: setup, sparring loop, and performance view."""
from __future__ import annotations

from nicegui import run, ui

from services.interview_controller import advance_session, evaluate_answer, start_session
from services.interview_llm import available as llm_available, interview_model, selectable_models
from storage.interview_store import (
    load_database, performance_summary, preferred_model, save_preferred_model,
)


MODE_HELP = {
    "Discussion": "A serious conversation with challenges and counterarguments; no constant scoring.",
    "Drill": "One focused question, a score, failure tags, and a concise critique after each answer.",
    "Simulation": "A realistic interview with no coaching until the final postmortem.",
    "Research Defense": "Hostile scrutiny of a thesis, model, project, presentation, or resume claim.",
}


def _inject_css() -> None:
    ui.add_head_html('''<style id="mq-interview-css">
        .interview-shell { width:100%; max-width:980px; margin:0 auto; }
        .interview-card {
            width:100%; background:var(--bg-card); border:1px solid var(--border-strong);
            border-radius:7px; padding:1.2rem; margin-bottom:1rem;
        }
        .interview-question {
            font-family:'IBM Plex Mono',monospace; font-size:clamp(1.15rem,2.4vw,1.75rem);
            line-height:1.45; color:var(--text-primary); padding:1.4rem 0 1.8rem;
        }
        .interview-kicker {
            font-size:0.62rem; font-weight:700; color:var(--accent); letter-spacing:0.18em;
            font-family:'IBM Plex Mono',monospace;
        }
        .interview-meta { color:var(--text-muted); font-size:0.72rem; }
        .interview-tag {
            display:inline-block; color:#fca5a5; background:#7f1d1d33; border:1px solid #f8717144;
            border-radius:4px; padding:2px 7px; margin:0 0.35rem 0.25rem 0; font-size:0.68rem;
        }
        .interview-stat {
            flex:1; min-width:150px; background:var(--bg-card); border:1px solid var(--border);
            border-radius:6px; padding:0.85rem 1rem;
        }
        .interview-stat-value { font-size:1.45rem; font-weight:700; color:var(--accent); }
        .interview-answer textarea { min-height:150px !important; line-height:1.55 !important; }
        .interview-feedback { border-left:3px solid var(--accent); padding:0.7rem 1rem; margin:1rem 0; }
        .interview-list-item { color:var(--text-muted); font-size:0.78rem; padding:0.2rem 0; }
        @media (max-width:640px) {
            .interview-card { padding:0.9rem; }
            .interview-question { padding:1rem 0 1.2rem; }
        }
    </style>''')


def _label(text: str) -> None:
    ui.label(text).classes("field-label")


def _stat(value: str, label: str) -> None:
    with ui.element("div").classes("interview-stat"):
        ui.label(value).classes("interview-stat-value")
        ui.label(label).classes("interview-meta")


def render_interview_practice() -> None:
    _inject_css()
    state = {
        "session": None,
        "pending": None,
        "retrying": False,
        "weakness_setup": False,
    }
    root = ui.element("div").classes("interview-shell")

    def refresh() -> None:
        root.clear()
        with root:
            session = state["session"]
            if session is None:
                _render_home(state, refresh)
            elif session.status == "completed":
                _render_postmortem(session, state, refresh)
            else:
                _render_session(session, state, refresh)

    refresh()


def _render_home(state: dict, refresh) -> None:
    summary = performance_summary()
    with ui.row().style("align-items:flex-start; justify-content:space-between; gap:0.75rem; flex-wrap:wrap; width:100%;"):
        with ui.column().style("gap:0.15rem;"):
            ui.label("INTERVIEW PRACTICE").classes("interview-kicker")
            ui.label("Think out loud. Defend the answer.").style(
                "font-size:1.15rem; font-weight:700; color:var(--text-primary);"
            )
        weakness_btn = ui.button("Practice My Weaknesses", icon="psychology").classes("submit-btn")

    with ui.row().style("gap:0.65rem; width:100%; margin:1rem 0; flex-wrap:wrap;"):
        _stat(str(summary["questions_answered"]), "questions answered")
        _stat(str(summary["sessions_completed"]), "sessions completed")
        _stat(str(len(summary["due"])), "concepts due")

    def weakness_setup() -> None:
        state["weakness_setup"] = True
        refresh()

    weakness_btn.on("click", weakness_setup)

    active = next((s for s in load_database().sessions if s.status == "active" and s.questions), None)
    if active:
        with ui.element("div").classes("interview-card").style("border-color:var(--accent);"):
            ui.label("CONTINUE WHERE YOU LEFT OFF").classes("interview-kicker")
            ui.label(
                f"{active.mode} · {active.topic} · question {len(active.questions)} of {active.target_questions}"
            ).style("font-size:0.86rem;font-weight:700;margin-top:0.35rem;")
            ui.label(f"Model · {active.model or interview_model()}").classes("interview-meta")

            def resume() -> None:
                state["session"] = active
                state["pending"] = active.pending_move or None
                state["retrying"] = bool(
                    active.questions[-1].answers and active.questions[-1].answers[-1].is_retry
                )
                refresh()

            ui.button("Resume Session", on_click=resume).classes("submit-btn").style("margin-top:0.7rem;")

    _render_setup(state, refresh)
    _render_performance(summary)


def _render_setup(state: dict, refresh) -> None:
    weakness = state["weakness_setup"]
    with ui.element("div").classes("interview-card"):
        ui.label("PRACTICE MY WEAKNESSES" if weakness else "START A SESSION").classes("interview-kicker")
        if weakness:
            ui.label("Recurring tags and due concepts will shape new question variants.").classes("interview-meta")

        with ui.row().style("gap:0.75rem; width:100%; align-items:flex-start; flex-wrap:wrap;"):
            with ui.column().style("gap:0; flex:1; min-width:220px;"):
                _label("MODE")
                mode = ui.select(
                    ["Discussion", "Drill", "Simulation", "Research Defense"],
                    value="Drill" if weakness else "Simulation",
                ).classes("w-full dark-input")
                mode_help = ui.label(MODE_HELP[mode.value]).classes("interview-meta").style(
                    "line-height:1.45;margin-top:0.3rem;"
                )
                mode.on(
                    "update:model-value",
                    lambda _: mode_help.set_text(MODE_HELP.get(mode.value, "")),
                )
            with ui.column().style("gap:0; flex:2; min-width:260px;"):
                _label("TOPIC")
                topic = ui.input(
                    value="Recurring weaknesses" if weakness else "",
                    placeholder="Macro, statistics, portfolio construction…",
                ).classes("w-full dark-input")

        with ui.row().style("gap:0.75rem; width:100%; align-items:flex-start; flex-wrap:wrap;"):
            with ui.column().style("gap:0; flex:1; min-width:220px;"):
                _label("ROLE (OPTIONAL)")
                role = ui.input(placeholder="Quant researcher, investment role…").classes("w-full dark-input")
            with ui.column().style("gap:0; flex:2; min-width:260px;"):
                _label("FOCUS AREAS (OPTIONAL)")
                focus = ui.input(placeholder="Mechanisms, concise answers, implementation…").classes("w-full dark-input")

        _label("JOB DESCRIPTION / MATERIALS (OPTIONAL)")
        materials = ui.textarea(
            placeholder="Paste a resume claim, job description, thesis, or research excerpt."
        ).classes("w-full dark-input")

        with ui.row().style("gap:0.75rem; align-items:flex-end; flex-wrap:wrap; margin-top:0.35rem;"):
            with ui.column().style("gap:0; min-width:180px;"):
                _label("SESSION LENGTH")
                length = ui.select(["10 questions", "20 questions", "30 questions", "Custom"], value="10 questions").classes("dark-input").style("width:180px;")
            custom = ui.number(value=10, min=1, max=50, label="Questions").classes("dark-input").style("width:120px;")
            custom.visible = False

            def length_changed() -> None:
                custom.visible = length.value == "Custom"

            length.on("update:model-value", lambda _: length_changed())

        _label("AI MODEL")
        selected_default = preferred_model() or interview_model()
        model_options = list(dict.fromkeys([selected_default, *selectable_models()]))
        model = ui.select(
            model_options,
            value=selected_default,
        ).classes("w-full dark-input")
        ui.label(
            "Saved as your default for future practice sessions."
        ).classes("interview-meta").style("margin-top:0.25rem;")

        status = ui.label("").style("color:#f87171; font-size:0.76rem; min-height:1.1rem; margin-top:0.5rem;")

        async def start() -> None:
            if not (topic.value or "").strip() and not (role.value or "").strip() and not weakness:
                status.set_text("Enter a topic or role.")
                return
            if not llm_available():
                status.set_text("Set OPENROUTER_API_KEY or INTERVIEW_API_KEY, then restart the app.")
                return
            count = int(custom.value or 10) if length.value == "Custom" else int(str(length.value).split()[0])
            chosen_model = model.value or interview_model()
            save_preferred_model(chosen_model)
            start_btn.disable()
            start_btn.set_text("Preparing first question…")
            try:
                session = await run.io_bound(lambda: start_session(
                    mode=mode.value,
                    topic=topic.value or role.value or "Recurring weaknesses",
                    role=role.value or "",
                    focus_areas=focus.value or "",
                    materials=materials.value or "",
                    target_questions=count,
                    weakness_session=weakness,
                    model=chosen_model,
                ))
            except Exception as exc:
                status.set_text(f"Could not start: {exc}")
                start_btn.enable()
                start_btn.set_text("Start Practice")
                return
            state.update(session=session, pending=None, retrying=False, weakness_setup=False)
            refresh()

        with ui.row().style("gap:0.65rem; align-items:center; margin-top:0.45rem;"):
            start_btn = ui.button("Start Practice", on_click=start).classes("submit-btn")
            if weakness:
                ui.button("Cancel", on_click=lambda: (state.update(weakness_setup=False), refresh())).classes("cancel-btn")
        ui.label("OpenAI-compatible via the configured API endpoint.").style(
            "color:var(--text-faint); font-size:0.62rem; margin-top:0.55rem;"
        )


def _render_session(session, state: dict, refresh) -> None:
    question = session.questions[-1]
    with ui.row().style("justify-content:space-between; align-items:center; width:100%; gap:0.75rem; flex-wrap:wrap;"):
        ui.label(f"{session.mode.upper()} · {session.topic}").classes("interview-kicker")
        ui.label(f"QUESTION {len(session.questions)} / {session.target_questions}").classes("interview-meta")
    ui.label(f"MODEL · {session.model or interview_model()}").style(
        "color:var(--text-faint);font-size:0.6rem;margin-top:0.25rem;"
    )

    with ui.element("div").classes("interview-card").style("margin-top:0.75rem;"):
        ui.label("INTERVIEWER").classes("interview-kicker")
        ui.label(question.text).classes("interview-question")

        pending = state["pending"]
        if session.mode == "Drill" and pending is not None:
            _render_drill_feedback(session, pending, state, refresh)
            return

        answer = ui.textarea(
            placeholder="Answer directly. Use structure, mechanisms, and evidence.",
        ).classes("w-full dark-input interview-answer")
        if state["retrying"]:
            ui.label("RETRY — give a materially better answer, not a cosmetic rewrite.").style(
                "color:#f59e0b; font-size:0.68rem; margin-top:0.4rem;"
            )
        error = ui.label("").style("color:#f87171; font-size:0.75rem; min-height:1rem;")

        async def dictate() -> None:
            mic.disable()
            mic.set_text("Listening…")
            try:
                transcript = await ui.run_javascript('''
                    return await new Promise((resolve) => {
                        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
                        if (!SpeechRecognition) { resolve('__UNSUPPORTED__'); return; }
                        const recognition = new SpeechRecognition();
                        recognition.lang = 'en-US'; recognition.continuous = false;
                        recognition.interimResults = false;
                        let finalText = '';
                        recognition.onresult = (event) => {
                            for (let i = event.resultIndex; i < event.results.length; i++) {
                                if (event.results[i].isFinal) finalText += event.results[i][0].transcript + ' ';
                            }
                        };
                        recognition.onerror = (event) => resolve('__ERROR__' + event.error);
                        recognition.onend = () => resolve(finalText.trim());
                        recognition.start();
                    });
                ''', timeout=75.0)
                if transcript == "__UNSUPPORTED__":
                    ui.notify("Speech recognition is not supported in this browser.", type="warning")
                elif str(transcript).startswith("__ERROR__"):
                    ui.notify(f"Microphone error: {str(transcript)[9:]}", type="negative")
                elif transcript:
                    existing = (answer.value or "").strip()
                    answer.set_value(f"{existing} {transcript}".strip())
            except Exception as exc:
                ui.notify(f"Speech input stopped: {exc}", type="warning")
            mic.enable()
            mic.set_text("Speak Answer")

        async def submit() -> None:
            text = (answer.value or "").strip()
            if not text:
                error.set_text("Answer the question, or say plainly that you do not know.")
                return
            submit_btn.disable()
            mic.disable()
            submit_btn.set_text("Evaluating…" if session.mode == "Drill" else "Continuing…")
            try:
                updated, result = await run.io_bound(lambda: evaluate_answer(
                    session.id, text, is_retry=state["retrying"],
                ))
                state["session"] = updated
                if result["done"]:
                    state["pending"] = None
                elif session.mode == "Drill":
                    state["pending"] = result
                else:
                    state["session"] = await run.io_bound(lambda: advance_session(session.id, result))
                refresh()
            except Exception as exc:
                error.set_text(f"Could not continue: {exc}")
                submit_btn.enable()
                mic.enable()
                submit_btn.set_text("Submit Answer")

        with ui.row().style("gap:0.65rem; align-items:center; margin-top:0.8rem; flex-wrap:wrap;"):
            submit_btn = ui.button("Submit Answer", on_click=submit).classes("submit-btn")
            mic = ui.button("Speak Answer", icon="mic", on_click=dictate).classes("cancel-btn")
            ui.label("Speech becomes editable text before submission.").classes("interview-meta")


def _render_drill_feedback(session, result: dict, state: dict, refresh) -> None:
    score = result.get("score")
    with ui.element("div").classes("interview-feedback"):
        ui.label(f"SCORE  {score if score is not None else '—'} / 10").style("font-weight:700; color:var(--text-primary);")
        with ui.element("div").style("margin:0.4rem 0;"):
            for tag in result.get("failure_tags", []):
                ui.element("span").classes("interview-tag").text = tag
        ui.label(result.get("critique") or "No material failure identified.").style(
            "color:var(--text-muted); font-size:0.82rem; line-height:1.55; white-space:pre-wrap;"
        )

    async def next_question() -> None:
        try:
            state["session"] = await run.io_bound(lambda: advance_session(session.id, result))
            state["pending"] = None
            state["retrying"] = False
            refresh()
        except Exception as exc:
            ui.notify(f"Could not continue: {exc}", type="negative")

    def retry() -> None:
        state["pending"] = None
        state["retrying"] = True
        refresh()

    with ui.row().style("gap:0.65rem; margin-top:0.7rem;"):
        materially_weak = score is not None and score <= 5
        if materially_weak and not state["retrying"]:
            ui.button("Retry Once", on_click=retry).classes("submit-btn")
        ui.button("Next Question", on_click=next_question).classes("cancel-btn")


def _render_postmortem(session, state: dict, refresh) -> None:
    post = session.postmortem
    ui.label("SESSION COMPLETE").classes("interview-kicker")
    ui.label(f"{session.mode} · {session.topic} · {len(session.questions)} questions").classes("interview-meta")
    with ui.element("div").classes("interview-card").style("margin-top:0.8rem;"):
        ui.label("OVERALL PERFORMANCE").classes("section-header")
        ui.label(post.overall_performance if post else "Session completed.").style("line-height:1.6;")
        if post:
            _postmortem_list("BIGGEST RECURRING PROBLEMS", post.biggest_problems[:3])
            _postmortem_list("STRONGEST AREAS", post.strongest_areas[:3])
            _postmortem_list("QUESTIONS / CONCEPTS TO REPEAT", post.concepts_to_repeat)
            if post.root_causes:
                ui.label("ROOT-CAUSE BREAKDOWN").classes("section-header").style("margin-top:1rem;")
                for category in ("knowledge", "evidence/research", "reasoning", "communication", "pressure handling"):
                    detail = post.root_causes.get(category, "")
                    if detail:
                        ui.label(f"{category.upper()} — {detail}").classes("interview-list-item")

    def new_session() -> None:
        state.update(session=None, pending=None, retrying=False, weakness_setup=False)
        refresh()

    ui.button("Start Another Session", on_click=new_session).classes("submit-btn")


def _postmortem_list(title: str, items: list[str]) -> None:
    if not items:
        return
    ui.label(title).classes("section-header").style("margin-top:1rem;")
    for item in items:
        ui.label(f"• {item}").classes("interview-list-item")


def _render_performance(summary: dict) -> None:
    with ui.element("div").classes("interview-card"):
        ui.label("PERFORMANCE").classes("interview-kicker")
        tag_total = summary["tag_total"] or 1
        if summary["tag_counts"]:
            ui.label("MOST COMMON ISSUES").classes("field-label")
            for tag, count in summary["tag_counts"].most_common(5):
                ui.label(f"{tag:<24} {count / tag_total:>5.0%}").classes("interview-list-item")
        else:
            ui.label("Complete a session to reveal recurring failure patterns.").classes("interview-list-item")

        with ui.row().style("gap:2rem; width:100%; flex-wrap:wrap; margin-top:0.6rem;"):
            with ui.column().style("gap:0; flex:1; min-width:220px;"):
                ui.label("IMPROVING").classes("field-label")
                for topic in summary["improving"] or ["Not enough history yet"]:
                    ui.label(topic).classes("interview-list-item")
            with ui.column().style("gap:0; flex:1; min-width:220px;"):
                ui.label("NEEDS WORK").classes("field-label")
                topics = [topic for topic, _ in summary["weak_topics"].most_common(5)]
                for topic in topics or ["No recurring weak topics yet"]:
                    ui.label(topic).classes("interview-list-item")
            with ui.column().style("gap:0; flex:1; min-width:220px;"):
                ui.label("DUE FOR REVIEW").classes("field-label")
                for item in summary["due"][:5] or [{"concept": "Nothing due"}]:
                    ui.label(item["concept"]).classes("interview-list-item")
