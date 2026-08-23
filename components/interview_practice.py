"""Active interview practice UI: setup, sparring loop, and performance view."""
from __future__ import annotations

from nicegui import run, ui

from services.interview_controller import advance_session, evaluate_answer, start_session
from services.interview_llm import available as llm_available, interview_model, selectable_models
from services.interview_prompts import (
    PRESETS, PROMPT_PACK_VERSION, built_in_prompt, get_preset,
)
from components.interview_speech import (
    cancel_recording, download_recording, start_recording, stop_recording,
    transcribe_recording,
)
from storage.interview_store import (
    load_database, performance_summary, preferred_model, save_preferred_model,
)
from services.topic_views import views_context
from storage.persistence import load_state


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
        .interview-recording-panel {
            margin-top:0.7rem; padding:0.75rem; border:1px solid var(--border);
            border-radius:6px; background:var(--bg-input);
        }
        .interview-recording-status {
            color:#f87171; font-size:0.72rem; font-weight:700;
            font-family:'IBM Plex Mono',monospace;
        }
        .interview-audio-track {
            width:100%; height:4px; margin:0.55rem 0; overflow:hidden;
            border-radius:4px; background:var(--border-strong);
        }
        .interview-audio-level {
            width:0; height:100%; transition:width 80ms linear;
            background:linear-gradient(90deg,var(--accent),#4ade80);
        }
        .interview-live-caption {
            min-height:1.1rem; color:var(--text-muted); font-size:0.75rem;
            line-height:1.45; font-style:italic;
        }
        .interview-quick {
            width:calc(33.333% - 0.55rem); min-width:220px; min-height:88px;
            align-items:flex-start !important; text-align:left; padding:0.8rem !important;
            border:1px solid var(--border-strong); background:var(--bg-card);
        }
        .interview-quick .q-btn__content {
            align-items:flex-start; text-align:left; white-space:pre-line;
        }
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


def render_interview_practice(app_state=None, launch_bridge=None, review_view=None) -> None:
    _inject_css()
    state = {
        "session": None,
        "pending": None,
        "retrying": False,
        "weakness_setup": False,
        "selected_preset": None,
        "view_setup": None,
        "review_view": review_view,
        "app_state": app_state,
    }
    root = ui.element("div").classes("interview-shell")

    def refresh() -> None:
        root.clear()
        with root:
            session = state["session"]
            if session is None:
                if state["view_setup"]:
                    _render_view_setup(state, refresh, app_state)
                else:
                    _render_home(state, refresh, app_state)
            elif session.status == "completed":
                _render_postmortem(session, state, refresh)
            else:
                _render_session(session, state, refresh)

    if launch_bridge is not None:
        def open_views(view_ids, style="Deliver"):
            state.update(session=None, pending=None, retrying=False, view_setup={"ids": list(view_ids), "style": style})
            refresh()
        launch_bridge["open"] = open_views
    refresh()


def _render_home(state: dict, refresh, app_state=None) -> None:
    summary = performance_summary()
    active_views = [view for view in (app_state.topic_views if app_state else []) if not view.archived]
    with ui.row().style("align-items:flex-start; justify-content:space-between; gap:0.75rem; flex-wrap:wrap; width:100%;"):
        with ui.column().style("gap:0.15rem;"):
            ui.label("INTERVIEW PRACTICE").classes("interview-kicker")
            ui.label("Think out loud. Defend the answer.").style(
                "font-size:1.15rem; font-weight:700; color:var(--text-primary);"
            )
        primary_action = ui.button(
            "Surprise Me" if active_views else "Start Practicing",
            icon="shuffle" if active_views else "psychology",
        ).classes("submit-btn")

    with ui.row().style("gap:0.65rem; width:100%; margin:1rem 0; flex-wrap:wrap;"):
        _stat(str(summary["questions_answered"]), "questions answered")
        _stat(str(summary["sessions_completed"]), "sessions completed")
        _stat(str(len(summary["due"])), "concepts due")

    def weakness_setup() -> None:
        state["weakness_setup"] = True
        state["selected_preset"] = "weaknesses"
        refresh()

    def surprise() -> None:
        ranked = sorted(active_views, key=lambda view: (
            0 if view.priority == "Core" else 1,
            view.practice.last_practiced is not None,
            view.practice.last_practiced or view.created_at,
        ))
        state["view_setup"] = {"ids": [ranked[0].id], "style": "Deliver"}
        refresh()

    primary_action.on("click", surprise if active_views else weakness_setup)

    if active_views:
        _render_views_quick_start(state, refresh, app_state)

    active = next((s for s in load_database().sessions if s.status == "active" and s.questions), None)
    if active:
        active_preset = get_preset(active.preset_key, active.mode)
        with ui.element("div").classes("interview-card").style("border-color:var(--accent);"):
            ui.label("CONTINUE WHERE YOU LEFT OFF").classes("interview-kicker")
            ui.label(
                f"{active_preset.label} · {active.topic} · question {len(active.questions)} of {active.target_questions}"
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

    ui.label("QUICK START").classes("interview-kicker").style("margin:0.4rem 0 0.65rem;")
    with ui.row().style("gap:0.75rem; width:100%; align-items:stretch; flex-wrap:wrap; margin-bottom:1rem;"):
        for preset in (item for key, item in PRESETS.items() if not key.startswith("view_")):
            def select_preset(_, key=preset.key) -> None:
                state["selected_preset"] = key
                state["weakness_setup"] = key == "weaknesses"
                refresh()

            ui.button(
                f"{preset.label}\n{preset.description}",
                on_click=select_preset,
            ).classes("interview-quick").props("no-caps flat")

    if state["selected_preset"]:
        _render_setup(state, refresh)
    _render_performance(summary)


def _render_views_quick_start(state: dict, refresh, app_state) -> None:
    active = [view for view in app_state.topic_views if not view.archived]
    if not active:
        return
    with ui.element("div").classes("interview-card").style("border-color:var(--accent);margin-top:.9rem"):
        ui.label("PRACTICE FROM · MY VIEWS").classes("interview-kicker")
        ui.label("Select one View or several for a mixed session. Stored structure is passed automatically.").classes("interview-meta").style("margin:.3rem 0 .7rem")
        options = {view.id: view.name for view in active}
        selected = ui.select(options, label="My Views", multiple=True).props("use-chips").classes("w-full dark-input")
        style = ui.toggle(["Deliver", "Discuss", "Defend"], value="Deliver").props("no-caps")
        def configure(ids=None):
            chosen = list(ids or selected.value or [])
            if not chosen:
                ui.notify("Select at least one View.", type="warning"); return
            state["view_setup"] = {"ids": chosen, "style": style.value or "Deliver"}; refresh()
        def surprise():
            ranked = sorted(active, key=lambda view: (
                0 if view.priority == "Core" else 1,
                view.practice.last_practiced is not None,
                view.practice.last_practiced or view.created_at,
            ))
            configure([ranked[0].id])
        with ui.row().style("gap:.5rem;flex-wrap:wrap;margin-top:.65rem"):
            ui.button("Begin", icon="play_arrow", on_click=lambda: configure()).classes("submit-btn")
            ui.button("Surprise Me", icon="shuffle", on_click=surprise).classes("cancel-btn")


def _render_view_setup(state: dict, refresh, app_state) -> None:
    setup = state["view_setup"] or {}
    views = [view for view in (app_state.topic_views if app_state else []) if view.id in setup.get("ids", [])]
    if not views:
        state["view_setup"] = None; refresh(); return
    style = setup.get("style", "Deliver")
    preset_key = f"view_{style.lower()}"
    preset = get_preset(preset_key)
    with ui.element("div").classes("interview-card").style("border-color:var(--accent)"):
        ui.label(f"{style.upper()} · MY VIEWS").classes("interview-kicker")
        ui.label(" + ".join(view.name for view in views)).style("font-size:1.15rem;font-weight:700;margin:.35rem 0")
        ui.label(preset.description).classes("interview-meta")
        if style == "Deliver" and len(views) > 1:
            ui.label("Mixed Deliver sessions move between selected Views; each answer is evaluated semantically, not word-for-word.").classes("interview-meta")
        status = ui.label("").style("color:#f87171;font-size:.75rem;min-height:1rem;margin-top:.6rem")
        async def start():
            if not llm_available(): status.set_text("Set OPENROUTER_API_KEY or INTERVIEW_API_KEY, then restart the app."); return
            button.disable(); button.set_text("Preparing…")
            try:
                session = await run.io_bound(lambda: start_session(
                    mode=preset.mode, preset_key=preset.key,
                    topic=" / ".join(view.name for view in views),
                    materials="", view_ids=[view.id for view in views],
                    practice_style=style, view_context=views_context(views),
                    target_questions=(len(views) if style == "Deliver" else preset.default_questions),
                    model=preferred_model() or interview_model(),
                ))
            except Exception as exc:
                status.set_text(f"Could not start: {exc}"); button.enable(); button.set_text("Begin"); return
            state.update(session=session, pending=None, retrying=False, view_setup=None); refresh()
        with ui.row().style("gap:.55rem;margin-top:.75rem"):
            button = ui.button("Begin", icon="play_arrow", on_click=start).classes("submit-btn")
            ui.button("Cancel", on_click=lambda: (state.update(view_setup=None), refresh())).classes("cancel-btn")


def _render_setup(state: dict, refresh) -> None:
    preset = get_preset(state["selected_preset"])
    weakness = preset.key == "weaknesses"
    with ui.element("div").classes("interview-card"):
        ui.label(preset.label.upper()).classes("interview-kicker")
        ui.label(preset.description).classes("interview-meta").style("margin:0.3rem 0 0.8rem;")

        with ui.row().style("gap:0.75rem; width:100%; align-items:flex-start; flex-wrap:wrap;"):
            with ui.column().style("gap:0; flex:2; min-width:260px;"):
                _label("TOPIC")
                topic = ui.input(
                    value="Focus areas" if weakness else "",
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

        _label("SESSION LENGTH")
        question_count = ui.number(
            value=preset.default_questions, min=1, max=50, label="Questions",
        ).classes("dark-input").style("width:140px;")

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

        with ui.expansion("Advanced prompt settings", icon="tune").classes("w-full").style(
            "margin-top:0.65rem;"
        ):
            ui.label(f"Built-in prompt pack · {PROMPT_PACK_VERSION}").classes("interview-meta")
            _label("BUILT-IN PROMPT (READ ONLY)")
            ui.textarea(
                value=built_in_prompt(preset.key, preset.mode),
            ).classes("w-full dark-input").props("readonly").style("max-height:260px;")
            _label("CUSTOM PROMPT OVERRIDE (OPTIONAL)")
            prompt_override = ui.textarea(
                placeholder=(
                    "Leave blank to execute the versioned built-in prompt. "
                    "A value here replaces the base and selected preset for this session."
                )
            ).classes("w-full dark-input")
            ui.label(
                "Advanced overrides are saved only on the session; ordinary Quick Start uses the built-in prompt."
            ).classes("interview-meta")

        status = ui.label("").style("color:#f87171; font-size:0.76rem; min-height:1.1rem; margin-top:0.5rem;")

        async def start() -> None:
            if not llm_available():
                status.set_text("Set OPENROUTER_API_KEY or INTERVIEW_API_KEY, then restart the app.")
                return
            count = int(question_count.value or preset.default_questions)
            chosen_model = model.value or interview_model()
            save_preferred_model(chosen_model)
            start_btn.disable()
            start_btn.set_text("Preparing first question…")
            try:
                session = await run.io_bound(lambda: start_session(
                    mode=preset.mode,
                    preset_key=preset.key,
                    prompt_override=prompt_override.value or "",
                    topic=topic.value or role.value or preset.label,
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
            state.update(
                session=session, pending=None, retrying=False,
                weakness_setup=False, selected_preset=None,
            )
            refresh()

        with ui.row().style("gap:0.65rem; align-items:center; margin-top:0.45rem;"):
            start_btn = ui.button("Start Practice", on_click=start).classes("submit-btn")
            ui.button(
                "Cancel",
                on_click=lambda: (
                    state.update(weakness_setup=False, selected_preset=None),
                    refresh(),
                ),
            ).classes("cancel-btn")
        ui.label("OpenAI-compatible via the configured API endpoint.").style(
            "color:var(--text-faint); font-size:0.62rem; margin-top:0.55rem;"
        )


def _render_session(session, state: dict, refresh) -> None:
    question = session.questions[-1]
    preset = get_preset(session.preset_key, session.mode)
    with ui.row().style("justify-content:space-between; align-items:center; width:100%; gap:0.75rem; flex-wrap:wrap;"):
        ui.label(f"{preset.label.upper()} · {session.topic}").classes("interview-kicker")
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

        with ui.element("div").classes("interview-recording-panel") as recording_panel:
            recording_status = ui.label("Microphone ready").classes("interview-recording-status")
            with ui.element("div").classes("interview-audio-track"):
                ui.element("div").classes("interview-audio-level")
            live_caption = ui.label("").classes("interview-live-caption")
        recording_panel.visible = False
        fallback_preview = {"text": ""}
        voice_draft = {"base": "", "draft": "", "full": ""}
        improved_ready = {"text": ""}

        def combined(base: str, text: str) -> str:
            return f"{base.strip()} {text.strip()}".strip()

        def append_transcript(text: str) -> str:
            value = combined(answer.value or "", text)
            answer.set_value(value)
            return value

        def insert_live_draft(text: str) -> None:
            base = (answer.value or "").strip()
            full = combined(base, text)
            voice_draft.update(base=base, draft=text.strip(), full=full)
            answer.set_value(full)

        def set_idle(record_more: bool = False) -> None:
            submit_btn.enable()
            mic.visible = True
            mic.disable()
            mic.set_text("Record More" if record_more else "Speak Answer")
            mic.enable()
            stop_btn.visible = False
            cancel_voice_btn.visible = False

        def handle_transcription(result: dict) -> None:
            if result.get("ok"):
                improved = str(result.get("text") or "").strip()
                current = (answer.value or "").strip()
                if voice_draft["full"] and current == voice_draft["full"]:
                    answer.set_value(combined(voice_draft["base"], improved))
                elif voice_draft["full"]:
                    improved_ready["text"] = improved
                    live_caption.set_text(f"Improved transcript: {improved}")
                    use_preview_btn.set_text("Replace with Improved")
                    use_preview_btn.visible = True
                    recording_status.set_text("Improved transcript ready · live draft was edited")
                else:
                    append_transcript(improved)
                device = result.get("device") or "local"
                model_name = result.get("model") or "speech model"
                if not improved_ready["text"]:
                    recording_status.set_text(
                        f"Improved with {model_name} on {device} · review before submitting"
                    )
                error.set_text("")
                retry_voice_btn.visible = False
                download_voice_btn.visible = False
                if not improved_ready["text"]:
                    use_preview_btn.visible = False
                fallback_preview["text"] = ""
                if not improved_ready["text"]:
                    voice_draft.update(base="", draft="", full="")
                set_idle(record_more=True)
                return
            message = str(result.get("error") or "Transcription failed.")
            recording_status.set_text("Audio retained for recovery")
            error.set_text(message)
            retryable = bool(result.get("retryable"))
            fallback_preview["text"] = str(result.get("preview") or "").strip()
            retry_voice_btn.visible = retryable
            download_voice_btn.visible = retryable
            use_preview_btn.visible = bool(fallback_preview["text"]) and not voice_draft["full"]
            use_preview_btn.set_text("Use Live Captions")
            mic.visible = not retryable
            if not retryable:
                mic.enable()
            stop_btn.visible = False
            cancel_voice_btn.visible = retryable
            cancel_voice_btn.set_text("Discard Recording")
            submit_btn.enable()

        async def begin_voice() -> None:
            error.set_text("")
            mic.disable()
            submit_btn.disable()
            try:
                result = await start_recording()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            if not result.get("ok"):
                error.set_text(str(result.get("error") or "Could not start recording."))
                set_idle()
                return
            recording_panel.visible = True
            recording_status.set_text("Recording 00:00 · pauses are safe")
            mic.visible = False
            stop_btn.visible = True
            stop_btn.enable()
            cancel_voice_btn.visible = True
            cancel_voice_btn.set_text("Cancel")

        async def finish_voice() -> None:
            stop_btn.disable()
            cancel_voice_btn.disable()
            recording_status.set_text("Stopping recording…")
            try:
                result = await stop_recording()
            except Exception as exc:
                result = {"ok": False, "error": str(exc), "retryable": False}
            if result.get("ok"):
                preview = str(result.get("preview") or "").strip()
                if preview:
                    insert_live_draft(preview)
                    live_caption.set_text("")
                    recording_status.set_text(
                        "Live draft inserted · review it or improve with local transcription"
                    )
                else:
                    recording_status.set_text(
                        "Audio recorded · no live captions were available"
                    )
                fallback_preview["text"] = preview
                retry_voice_btn.set_text("Improve Transcript")
                retry_voice_btn.visible = True
                download_voice_btn.visible = True
                use_preview_btn.visible = False
                mic.visible = False
                stop_btn.visible = False
                cancel_voice_btn.visible = True
                cancel_voice_btn.set_text("Discard Audio")
                submit_btn.enable()
            else:
                handle_transcription(result)
            cancel_voice_btn.enable()

        async def retry_voice() -> None:
            retry_voice_btn.disable()
            recording_status.set_text("Improving with local transcription…")
            context = f"{session.topic}. {question.text}. {session.role} {session.focus_areas}"
            try:
                result = await transcribe_recording(context)
            except Exception as exc:
                result = {"ok": False, "error": str(exc), "retryable": True}
            retry_voice_btn.enable()
            handle_transcription(result)

        async def discard_voice() -> None:
            await cancel_recording()
            fallback_preview["text"] = ""
            retry_voice_btn.visible = False
            download_voice_btn.visible = False
            use_preview_btn.visible = False
            recording_status.set_text("Recording discarded")
            error.set_text("")
            set_idle()

        async def save_audio() -> None:
            if not await download_recording():
                ui.notify("No recoverable audio is available.", type="warning")

        def use_preview() -> None:
            if improved_ready["text"]:
                answer.set_value(combined(voice_draft["base"], improved_ready["text"]))
                improved_ready["text"] = ""
                voice_draft.update(base="", draft="", full="")
                live_caption.set_text("")
                use_preview_btn.visible = False
                recording_status.set_text("Improved transcript inserted · review before submitting")
            elif fallback_preview["text"]:
                append_transcript(fallback_preview["text"])
                retry_voice_btn.visible = False
                use_preview_btn.visible = False
                recording_status.set_text("Live captions inserted · audio remains available")
            submit_btn.enable()

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
                    _sync_view_metadata(state.get("app_state"), updated.view_ids)
                elif session.mode == "Drill":
                    state["pending"] = result
                else:
                    state["session"] = await run.io_bound(lambda: advance_session(session.id, result))
                await cancel_recording()
                refresh()
            except Exception as exc:
                error.set_text(f"Could not continue: {exc}")
                submit_btn.enable()
                mic.enable()
                submit_btn.set_text("Submit Answer")

        with ui.row().style("gap:0.65rem; align-items:center; margin-top:0.8rem; flex-wrap:wrap;"):
            submit_btn = ui.button("Submit Answer", on_click=submit).classes("submit-btn")
            mic = ui.button("Speak Answer", icon="mic", on_click=begin_voice).classes("cancel-btn")
            stop_btn = ui.button("Stop & Use Live Draft", icon="stop", on_click=finish_voice).classes("submit-btn")
            cancel_voice_btn = ui.button("Cancel", on_click=discard_voice).classes("cancel-btn")
            retry_voice_btn = ui.button("Improve Transcript", on_click=retry_voice).classes("submit-btn")
            use_preview_btn = ui.button("Use Live Captions", on_click=use_preview).classes("cancel-btn")
            download_voice_btn = ui.button("Download Audio", on_click=save_audio).classes("cancel-btn")
            stop_btn.visible = False
            cancel_voice_btn.visible = False
            retry_voice_btn.visible = False
            use_preview_btn.visible = False
            download_voice_btn.visible = False
            ui.label("Recording continues through pauses and becomes editable text.").classes("interview-meta")


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
    preset = get_preset(session.preset_key, session.mode)
    ui.label("SESSION COMPLETE").classes("interview-kicker")
    ui.label(f"{preset.label} · {session.topic} · {len(session.questions)} questions").classes("interview-meta")
    with ui.element("div").classes("interview-card").style("margin-top:0.8rem;"):
        if preset.key not in {"maintenance_20", "weaknesses"}:
            ui.label("OVERALL").classes("section-header")
            ui.label(post.overall_performance if post else "Session completed.").style("line-height:1.6;")
        if post:
            if preset.key == "view_deliver":
                _postmortem_list("COVERED", post.strongest_areas)
                _postmortem_list("MISSED / WEAK", post.biggest_problems)
                delivery = [post.root_causes.get("communication", "")] if post.root_causes.get("communication") else []
                _postmortem_list("DELIVERY", delivery or ([post.overall_performance] if post.overall_performance else []))
            elif preset.key == "maintenance_20":
                _postmortem_list("STRONG", post.strongest_areas[:1])
                _postmortem_list("WORK ON", post.biggest_problems[:1])
                _postmortem_list("REPEAT", post.concepts_to_repeat[:1])
            elif preset.key == "weaknesses":
                _postmortem_list("IMPROVED", post.strongest_areas)
                _postmortem_list("STILL WEAK", post.biggest_problems)
                _postmortem_list("NEXT PRIORITY", post.concepts_to_repeat[:1])
            else:
                _postmortem_list(
                    "THREE BIGGEST RISKS" if preset.key == "job_interview" else "TOP FIXES",
                    post.biggest_problems[:3],
                )
                _postmortem_list("STRONGEST AREAS", post.strongest_areas[:3])
                _postmortem_list("REPEAT NEXT TIME", post.concepts_to_repeat)
            if post.root_causes:
                ui.label("ROOT-CAUSE BREAKDOWN").classes("section-header").style("margin-top:1rem;")
                for category in ("knowledge", "evidence/research", "reasoning", "communication", "pressure handling"):
                    detail = post.root_causes.get(category, "")
                    if detail:
                        ui.label(f"{category.upper()} — {detail}").classes("interview-list-item")
            if post.trend:
                ui.label("TREND").classes("section-header").style("margin-top:1rem;")
                ui.label(post.trend).classes("interview-list-item")

    def new_session() -> None:
        state.update(
            session=None, pending=None, retrying=False,
            weakness_setup=False, selected_preset=None,
        )
        refresh()

    with ui.row().style("gap:.55rem;flex-wrap:wrap"):
        if session.view_ids:
            ui.button("Try Again", on_click=lambda: (state.update(session=None, pending=None, retrying=False, view_setup={"ids": session.view_ids, "style": session.practice_style or "Deliver"}), refresh())).classes("submit-btn")
            if session.practice_style != "Defend":
                ui.button("Practice Defense", on_click=lambda: (state.update(session=None, pending=None, retrying=False, view_setup={"ids": session.view_ids, "style": "Defend"}), refresh())).classes("cancel-btn")
            if state.get("review_view") and len(session.view_ids) == 1:
                ui.button("Review This View", icon="edit_note", on_click=lambda: state["review_view"](session.view_ids[0])).classes("cancel-btn")
        ui.button("Start Another Session", on_click=new_session).classes("cancel-btn" if session.view_ids else "submit-btn")


def _sync_view_metadata(app_state, view_ids: list[str]) -> None:
    """Reflect controller-persisted practice metadata without forcing a page reload."""
    if app_state is None or not view_ids:
        return
    fresh = load_state()
    by_id = {view.id: view for view in fresh.topic_views}
    for view in app_state.topic_views:
        if view.id in view_ids and view.id in by_id:
            view.practice = by_id[view.id].practice


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
            ui.label("Complete a session to see your practice insights.").classes("interview-list-item")

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
