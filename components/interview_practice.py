"""Active interview practice UI: setup, quant model library, sparring loop, and performance view."""
from __future__ import annotations

import random
from datetime import date
from pathlib import Path

from nicegui import run, ui

from services.interview_controller import (
    abandon_session, advance_session, answer_tips, evaluate_answer, start_session,
)
from services.interview_llm import available as llm_available, interview_model, selectable_models
from services.interview_prompts import (
    PRESETS, PROMPT_PACK_VERSION, QUANT_FUNDAMENTALS_OPENERS,
    built_in_prompt, get_preset,
)
from components.interview_speech import (
    cancel_recording, start_recording, stop_recording,
)
from components.interview_tts import speak_question, stop_speaking
from storage.interview_store import (
    load_database, model_practice_stats, performance_summary,
    preferred_model, save_preferred_model,
)
from storage.model_library import (
    ModelNote, find_comparison_note, model_context_for, models_folder_path,
    scan_model_notes,
)
from storage.user_settings import (
    interview_tts_enabled, interview_tts_model, save_interview_tts_enabled,
    save_interview_tts_model,
)
import config as app_config
from services.topic_views import views_context
from storage.persistence import load_state


MODE_HELP = {
    "Discussion": "A serious conversation with challenges and counterarguments; no constant scoring.",
    "Drill": "One focused question, a score, failure tags, and a concise critique after each answer.",
    "Simulation": "A realistic interview with no coaching until the final postmortem.",
    "Research Defense": "Hostile scrutiny of a thesis, model, project, presentation, or resume claim.",
}

_MODEL_MODE_LABELS = {
    "explain": "Explain",
    "defend": "Defend",
    "compare": "Compare",
    "deep_dive": "Deep Dive",
}
_MODEL_ROW_MODES = ("explain", "defend", "deep_dive")
_MODEL_PRESET_MODES = {f"model_{mode}": mode for mode in _MODEL_MODE_LABELS}
_MODEL_OPENERS = {
    "explain": "Walk me through {title}.",
    "defend": "Tell me why you would choose {title} over the obvious alternative.",
    "deep_dive": "Let's go deep on {title}: what exactly is it optimizing?",
}


def _model_opener(mode: str, title: str) -> str:
    return _MODEL_OPENERS[mode].format(title=title)


def _compare_opener(a: ModelNote, b: ModelNote) -> str:
    return (
        f"I know both {a.title} and {b.title}. What is the real difference, "
        "and when would you pick one over the other?"
    )


def _library_status_text(folder: Path | None, notes: list[ModelNote]) -> str:
    if folder is None:
        return "No Models folder configured — set it in ··· → Settings."
    if not folder.exists():
        return f"Models folder unavailable: {folder} — generic practice still works."
    return f"{len(notes)} notes · {folder}"


def _model_stats_line(entry: dict | None) -> str:
    by_style = (entry or {}).get("by_style") or {}
    dated = [(style, info) for style, info in by_style.items() if info.get("last")]
    if not dated:
        return "Not practiced yet"
    _, latest_info = max(dated, key=lambda item: item[1]["last"])
    days = max(0, (date.today() - latest_info["last"]).days)
    when = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
    scored = [
        (style, info["avg_score"])
        for style, info in by_style.items()
        if info.get("avg_score") is not None
    ]
    if scored:
        best_style, best_avg = max(scored, key=lambda item: item[1])
        return f"Last practiced {when} · best: {best_style} {best_avg:g}/10"
    return f"Last practiced {when}"


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
        .interview-tts-status {
            color:var(--text-faint); font-size:0.68rem; min-height:1rem;
            font-family:'IBM Plex Mono',monospace;
        }
        .interview-shortcuts {
            color:var(--text-faint); font-size:0.66rem; line-height:1.45;
            font-family:'IBM Plex Mono',monospace;
        }
        .interview-quick {
            width:calc(33.333% - 0.55rem); min-width:220px; min-height:88px;
            align-items:flex-start !important; text-align:left; padding:0.8rem !important;
            border:1px solid var(--border-strong); background:var(--bg-card);
        }
        .interview-quick .q-btn__content {
            align-items:flex-start; text-align:left; white-space:pre-line;
        }
        .interview-quant-row {
            display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; margin-top:0.55rem;
        }
        .interview-model-row {
            display:flex; align-items:center; justify-content:space-between; gap:0.75rem;
            flex-wrap:wrap; border:1px solid var(--border); border-radius:6px;
            padding:0.65rem 0.8rem; margin-bottom:0.5rem; background:var(--bg-input);
        }
        .interview-model-tags { color:var(--text-muted); font-size:0.68rem; }
        @media (max-width:640px) {
            .interview-card { padding:0.9rem; }
            .interview-question { padding:1rem 0 1.2rem; }
        }
    </style>''')


def _label(text: str) -> None:
    ui.label(text).classes("field-label")


def render_interview_practice(app_state=None, launch_bridge=None, review_view=None) -> None:
    _inject_css()
    state = {
        "session": None,
        "pending": None,
        "retrying": False,
        "weakness_setup": False,
        "selected_preset": None,
        "advanced_setup": False,
        "view_setup": None,
        "models_setup": None,
        "quant_session_note": None,
        "compare_sel": [],
        "review_view": review_view,
        "app_state": app_state,
        "tts_enabled": interview_tts_enabled(),
        "tts_model": interview_tts_model(),
        "last_tts_question": None,
    }
    root = ui.element("div").classes("interview-shell")

    def refresh() -> None:
        root.clear()
        with root:
            session = state["session"]
            if session is None:
                if state["view_setup"]:
                    _render_view_setup(state, refresh, app_state)
                elif state["models_setup"]:
                    _render_model_library(state, refresh)
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
            "Surprise Me (Views)" if active_views else "Start Practicing",
            icon="shuffle" if active_views else "psychology",
        ).classes("submit-btn")

    def weakness_setup() -> None:
        state["weakness_setup"] = True
        state["selected_preset"] = "weaknesses"
        refresh()

    def surprise() -> None:
        """Pick one active My View and open a ready-to-start practice session."""
        selected = random.choice(active_views)
        state["view_setup"] = {
            "ids": [selected.id],
            "style": "Deliver",
            "surprise": True,
        }
        refresh()

    primary_action.on("click", surprise if active_views else weakness_setup)

    if active_views:
        _render_views_quick_start(state, refresh, app_state)

    _render_quant_practice_card(state, refresh)

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

    if state["advanced_setup"]:
        ui.label("ADVANCED SETUP · ALL MODES").classes("interview-kicker").style("margin:0.4rem 0 0.65rem;")
        with ui.row().style("gap:0.75rem; width:100%; align-items:stretch; flex-wrap:wrap; margin-bottom:1rem;"):
            for preset in (
                item for key, item in PRESETS.items()
                if not key.startswith("view_") and not key.startswith("model_")
            ):
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


def _render_quant_practice_card(state: dict, refresh) -> None:
    notes = scan_model_notes()
    status_text = _library_status_text(models_folder_path(), notes)

    def open_library(mode: str) -> None:
        state["models_setup"] = {"mode": mode}
        if mode == "compare":
            state["compare_sel"] = []
        refresh()

    async def start_fundamentals() -> None:
        if not llm_available():
            status.set_text("Configure an LLM provider and API key in Settings, then restart the app.")
            return
        fundamentals_btn.disable()
        fundamentals_btn.set_text("Preparing first question…")
        preset = get_preset("quant_drill")
        chosen_model = preferred_model() or interview_model()
        save_preferred_model(chosen_model)
        try:
            session = await run.io_bound(lambda: start_session(
                mode=preset.mode, preset_key=preset.key,
                topic="Quant fundamentals",
                initial_question=random.choice(QUANT_FUNDAMENTALS_OPENERS),
                practice_style="Fundamentals",
                target_questions=preset.default_questions,
                model=chosen_model,
            ))
        except Exception as exc:
            status.set_text(f"Could not start: {exc}")
            fundamentals_btn.enable()
            fundamentals_btn.set_text("Quant Fundamentals")
            return
        state.update(session=session, pending=None, retrying=False)
        refresh()

    async def surprise_quant() -> None:
        if not notes:
            await start_fundamentals()
            return
        note = random.choice(notes)
        mode = random.choice(_MODEL_ROW_MODES)
        preset = get_preset(f"model_{mode}")
        await _start_model_session(
            state, refresh,
            preset_key=preset.key, topic=note.title,
            initial_question=_model_opener(mode, note.title),
            notes=[note], style=_MODEL_MODE_LABELS[mode],
            target_questions=preset.default_questions,
            button=surprise_btn, status=status, button_label="Surprise Me (Quant)",
        )

    with ui.element("div").classes("interview-card").style("border-color:var(--accent);"):
        ui.label("QUANT PRACTICE").classes("interview-kicker")
        ui.label("Pick one of your model notes and start speaking in seconds — explain, defend, compare, or go deep.").classes(
            "interview-meta"
        ).style("margin:.3rem 0 .7rem;")
        with ui.row().classes("interview-quant-row"):
            ui.label("MY MODELS").classes("interview-kicker").style("min-width:5.4rem;")
            for mode, label in (
                ("explain", "Explain My Model"), ("defend", "Defend My Model"),
                ("compare", "Compare Models"), ("deep_dive", "Deep Dive"),
            ):
                model_btn = ui.button(label, on_click=lambda _, m=mode: open_library(m)).props("no-caps")
                if not notes:
                    model_btn.disable()
            ui.space()
            ui.button("Refresh Models", icon="refresh", on_click=lambda: refresh()).props(
                "flat dense no-caps"
            ).style("color:var(--text-muted);font-size:.72rem;")
        ui.label(status_text).classes("interview-meta").style("margin-bottom:.35rem;")
        with ui.row().classes("interview-quant-row"):
            ui.label("GENERAL").classes("interview-kicker").style("min-width:5.4rem;")
            fundamentals_btn = ui.button("Quant Fundamentals", on_click=start_fundamentals).props("no-caps")
            surprise_btn = ui.button(
                "Surprise Me (Quant)", icon="shuffle", on_click=surprise_quant,
            ).props("no-caps")
        with ui.row().classes("interview-quant-row"):
            ui.label("CUSTOM").classes("interview-kicker").style("min-width:5.4rem;")
            ui.button("Advanced Setup", icon="tune", on_click=lambda: (state.update(advanced_setup=True), refresh())).props("no-caps")
        status = ui.label("").style("color:#f87171; font-size:.75rem; min-height:1rem; margin-top:.3rem;")


async def _start_model_session(
    state: dict, refresh, *, preset_key: str, topic: str, initial_question: str,
    notes: list[ModelNote], style: str, target_questions: int,
    button=None, status=None, button_label: str = "Start",
) -> None:
    if not llm_available():
        if status is not None:
            status.set_text("Configure an LLM provider and API key in Settings, then restart the app.")
        return
    chosen_model = preferred_model() or interview_model()
    save_preferred_model(chosen_model)
    if button is not None:
        button.disable()
        button.set_text("Preparing first question…")
    try:
        session = await run.io_bound(lambda: start_session(
            mode="Drill", preset_key=preset_key, topic=topic,
            initial_question=initial_question,
            model_note_ids=[note.id for note in notes],
            model_note_titles=[note.title for note in notes],
            model_context=model_context_for(notes),
            practice_style=style,
            target_questions=target_questions,
            model=chosen_model,
        ))
    except Exception as exc:
        if status is not None:
            status.set_text(f"Could not start: {exc}")
        if button is not None:
            button.enable()
            button.set_text(button_label)
        return
    state.update(session=session, pending=None, retrying=False, models_setup=None)
    refresh()


def _render_model_library(state: dict, refresh) -> None:
    setup = state["models_setup"] or {}
    mode = setup.get("mode", "explain")
    notes = scan_model_notes()
    status_text = _library_status_text(models_folder_path(), notes)
    stats = model_practice_stats()
    highlight_id = state.get("quant_session_note")
    state["quant_session_note"] = None

    def go_back() -> None:
        state.update(models_setup=None, quant_session_note=None, compare_sel=[])
        refresh()

    def render_compare_bar() -> None:
        by_id = {note.id: note for note in notes}
        pair = [by_id[note_id] for note_id in state["compare_sel"] if note_id in by_id]
        if len(pair) < 2:
            ui.label("Select two models to compare.").classes("interview-meta")
            return
        a, b = pair
        preset = get_preset("model_compare")

        async def begin() -> None:
            context_notes = [a, b]
            comparison = find_comparison_note(notes, a, b)
            if comparison is not None:
                context_notes.append(comparison)
            await _start_model_session(
                state, refresh,
                preset_key=preset.key, topic=f"{a.title} vs {b.title}",
                initial_question=_compare_opener(a, b),
                notes=context_notes, style=_MODEL_MODE_LABELS["compare"],
                target_questions=preset.default_questions,
                button=begin_btn, status=status, button_label="Begin Compare",
            )

        with ui.row().style("gap:.55rem;align-items:center;margin-bottom:.6rem;flex-wrap:wrap;"):
            begin_btn = ui.button("Begin Compare", icon="play_arrow", on_click=begin).classes("submit-btn")
            ui.label(f"{a.title} vs {b.title}").classes("interview-meta")

    def render_note_row(note: ModelNote) -> None:
        with ui.element("div").classes("interview-model-row") as row:
            if note.id == highlight_id:
                row.style("border-color:var(--accent);")
            with ui.column().style("gap:.12rem;flex:1;min-width:240px;"):
                ui.label(note.title).style("font-size:1rem;font-weight:700;color:var(--text-primary);")
                if note.display_tags:
                    ui.label(" · ".join(note.display_tags)).classes("interview-model-tags")
                meta_parts = [
                    part for part in (
                        note.priority, note.status,
                        f"updated {note.updated_display}" if note.updated_display else "",
                    ) if part
                ]
                ui.label(" · ".join(meta_parts)).classes("interview-meta")
                ui.label(_model_stats_line(stats.get(note.id))).classes("interview-meta")
                if note.parse_warning:
                    ui.label(note.parse_warning).style("color:#f59e0b;font-size:.68rem;")
            if mode == "compare":
                selected = note.id in state["compare_sel"]

                def toggle_selection(_, target=note) -> None:
                    selection = state["compare_sel"]
                    if target.id in selection:
                        selection.remove(target.id)
                    else:
                        selection.append(target.id)
                        if len(selection) > 2:
                            selection.pop(0)
                    rebuild()

                ui.button(
                    icon="check_box" if selected else "check_box_outline_blank",
                    on_click=toggle_selection,
                ).props("flat dense").style("color:var(--accent);")
            else:
                for row_mode in _MODEL_ROW_MODES:
                    action_btn = ui.button(_MODEL_MODE_LABELS[row_mode]).props(
                        "flat dense no-caps"
                    ).style("color:var(--accent);font-size:.72rem;")

                    async def launch_action(_, target=action_btn, note_ref=note, row_variant=row_mode) -> None:
                        preset = get_preset(f"model_{row_variant}")
                        await _start_model_session(
                            state, refresh,
                            preset_key=preset.key, topic=note_ref.title,
                            initial_question=_model_opener(row_variant, note_ref.title),
                            notes=[note_ref], style=_MODEL_MODE_LABELS[row_variant],
                            target_questions=preset.default_questions,
                            button=target, status=status,
                            button_label=_MODEL_MODE_LABELS[row_variant],
                        )

                    action_btn.on("click", launch_action)

    with ui.element("div").classes("interview-card").style("border-color:var(--accent);"):
        with ui.row().style("justify-content:space-between;align-items:center;width:100%;gap:.6rem;flex-wrap:wrap;"):
            ui.label(f"MY MODELS · {_MODEL_MODE_LABELS[mode]}").classes("interview-kicker")
            with ui.row().style("gap:.4rem;"):
                ui.button("Refresh Models", icon="refresh", on_click=lambda: refresh()).props(
                    "flat dense no-caps"
                ).style("color:var(--text-muted);font-size:.72rem;")
                ui.button("Back", icon="arrow_back", on_click=go_back).props(
                    "flat dense no-caps"
                ).style("color:var(--text-muted);font-size:.72rem;")
        ui.label(status_text).classes("interview-meta").style("margin:.25rem 0 .6rem;")
        status = ui.label("").style("color:#f87171; font-size:.75rem; min-height:1rem;")
        if not notes:
            ui.label(
                "No model notes are available, so model practice is disabled here. "
                "The drills under GENERAL on the Practice home still work."
            ).classes("interview-list-item")
            return
        search = ui.input(placeholder="Filter by title or tag…").classes("w-full dark-input").props("dense")
        compare_bar = ui.element("div")
        listing = ui.element("div")

        def rebuild() -> None:
            query = (search.value or "").strip().lower()
            matches = [
                note for note in notes
                if not query
                or query in note.title.lower()
                or any(query in tag.lower() for tag in note.tags)
            ]
            compare_bar.clear()
            listing.clear()
            with compare_bar:
                if mode == "compare":
                    render_compare_bar()
            with listing:
                for note in matches:
                    render_note_row(note)

        search.on("update:model-value", lambda: rebuild())
        rebuild()


def _render_views_quick_start(state: dict, refresh, app_state) -> None:
    active = [view for view in app_state.topic_views if not view.archived]
    if not active:
        return
    with ui.element("div").classes("interview-card").style("border-color:var(--accent);"):
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
        with ui.row().style("gap:.5rem;flex-wrap:wrap;margin-top:.65rem"):
            ui.button("Begin", icon="play_arrow", on_click=lambda: configure()).classes("submit-btn")


def _render_view_setup(state: dict, refresh, app_state) -> None:
    setup = state["view_setup"] or {}
    views = [view for view in (app_state.topic_views if app_state else []) if view.id in setup.get("ids", [])]
    if not views:
        state["view_setup"] = None; refresh(); return
    style = setup.get("style", "Deliver")
    preset_key = f"view_{style.lower()}"
    preset = get_preset(preset_key)
    with ui.element("div").classes("interview-card").style("border-color:var(--accent)"):
        ui.label(
            "SURPRISE PICK · MY VIEWS" if setup.get("surprise") else f"{style.upper()} · MY VIEWS"
        ).classes("interview-kicker")
        ui.label(" + ".join(view.name for view in views)).style("font-size:1.15rem;font-weight:700;margin:.35rem 0")
        ui.label(
            "A random active View is ready for a Deliver session."
            if setup.get("surprise") else preset.description
        ).classes("interview-meta")
        if style == "Deliver" and len(views) > 1:
            ui.label("Mixed Deliver sessions move between selected Views; each answer is evaluated semantically, not word-for-word.").classes("interview-meta")
        default_model = preferred_model() or interview_model()
        model = ui.select(
            list(dict.fromkeys([default_model, *selectable_models()])),
            value=default_model, label="AI Model",
        ).classes("dark-input").style("min-width:260px;margin-top:.6rem")
        status = ui.label("").style("color:#f87171;font-size:.75rem;min-height:1rem;margin-top:.6rem")
        async def start():
            if not llm_available(): status.set_text("Configure an LLM provider and API key in Settings, then restart the app."); return
            button.disable(); button.set_text("Preparing…")
            chosen_model = model.value or interview_model()
            save_preferred_model(chosen_model)
            try:
                session = await run.io_bound(lambda: start_session(
                    mode=preset.mode, preset_key=preset.key,
                    topic=" / ".join(view.name for view in views),
                    materials="", view_ids=[view.id for view in views],
                    practice_style=style, view_context=views_context(views),
                    initial_question=(
                        f"What's your view on {views[0].name}?" if len(views) == 1 else ""
                    ),
                    target_questions=(len(views) if style == "Deliver" else preset.default_questions),
                    model=chosen_model,
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
                status.set_text("Configure an LLM provider and API key in Settings, then restart the app.")
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

    async def end_session() -> None:
        try:
            await stop_speaking()
            await cancel_recording()
            await run.io_bound(lambda: abandon_session(session.id))
            state.update(session=None, pending=None, retrying=False)
            refresh()
        except Exception as exc:
            ui.notify(f"Could not end session: {exc}", type="negative")

    with ui.dialog() as exit_dialog, ui.card().style("max-width:430px;"):
        ui.label("End this practice session?").style("font-size:1.05rem;font-weight:700;")
        ui.label(
            "Your submitted answers stay in your history, but this unfinished session will not be scored "
            "as completed or update My View practice metadata."
        ).classes("interview-meta").style("margin-top:.4rem;")
        with ui.row().style("justify-content:flex-end;gap:.55rem;margin-top:.9rem;"):
            ui.button("Keep Practicing", on_click=exit_dialog.close).classes("cancel-btn")
            ui.button("End Session", on_click=end_session).classes("submit-btn")

    with ui.row().style("justify-content:space-between; align-items:center; width:100%; gap:0.75rem; flex-wrap:wrap;"):
        with ui.column().style("gap:.15rem;"):
            ui.label(f"{preset.label.upper()} · {session.topic}").classes("interview-kicker")
            ui.label(f"QUESTION {len(session.questions)} / {session.target_questions}").classes("interview-meta")
        ui.button("Exit Session", icon="logout", on_click=exit_dialog.open).props(
            "flat dense no-caps"
        ).style("color:var(--text-muted);font-size:.72rem;")
    ui.label(f"MODEL · {session.model or interview_model()}").style(
        "color:var(--text-faint);font-size:0.6rem;margin-top:0.25rem;"
    )

    with ui.element("div").classes("interview-card").style("margin-top:0.75rem;"):
        with ui.row().style(
            "justify-content:space-between;align-items:center;width:100%;gap:.6rem;flex-wrap:wrap;"
        ):
            ui.label("INTERVIEWER").classes("interview-kicker")
            tts_toggle = ui.checkbox(
                "Read new questions aloud", value=state["tts_enabled"],
            ).props("dense").classes("interview-meta")
        ui.label(question.text).classes("interview-question")

        tts_status = ui.label(
            "TTS · waiting for question" if state["tts_enabled"]
            else "TTS · playback off"
        ).classes("interview-tts-status")

        async def play_question() -> None:
            try:
                result = await speak_question(question.text, state["tts_model"])
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            if result.get("ok"):
                state["last_tts_question"] = question.id
                tts_status.set_text("Reading question aloud")
            else:
                message = str(result.get("error") or "Could not play this question.")
                tts_status.set_text(message)
                ui.notify(message, type="warning")

        async def change_tts(_) -> None:
            enabled = bool(tts_toggle.value)
            state["tts_enabled"] = enabled
            save_interview_tts_enabled(enabled)
            if enabled:
                await play_question()
            else:
                await stop_speaking()
                tts_status.set_text("Automatic playback off")

        tts_toggle.on("update:model-value", change_tts)
        with ui.row().style("gap:.45rem;align-items:center;margin:.15rem 0 .8rem;flex-wrap:wrap;"):
            tts_model = ui.select(
                {
                    "google/gemini-3.1-flash-tts-preview": "Gemini 3.1 Flash TTS (default)",
                    "x-ai/grok-voice-tts-1.0": "Grok Voice TTS 1.0",
                    "deepgram/flux-tts:free": "Deepgram Flux TTS (free)",
                },
                value=state["tts_model"], label="TTS model",
            ).classes("dark-input").style("min-width:265px;")

            def change_tts_model(_) -> None:
                model = tts_model.value or app_config.INTERVIEW_TTS_MODEL_DEFAULT
                state["tts_model"] = model
                save_interview_tts_model(model)

            tts_model.on("update:model-value", change_tts_model)
            ui.button("Replay Question", icon="volume_up", on_click=play_question).props(
                "flat dense no-caps"
            ).style("color:var(--accent);font-size:.72rem;")
            ui.button("Stop", icon="stop", on_click=stop_speaking).props(
                "flat dense no-caps"
            ).style("color:var(--text-muted);font-size:.72rem;")

        if state["tts_enabled"] and state["last_tts_question"] != question.id:
            state["last_tts_question"] = question.id
            ui.timer(0.15, play_question, once=True)

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
        voice_active = {"value": False}
        submitting = {"value": False}
        tips_loading = {"value": False}

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
                else:
                    append_transcript(improved)
                device = result.get("device") or "local"
                model_name = result.get("model") or "speech model"
                recording_status.set_text(
                    f"Transcript ready with {model_name} on {device} · review before submitting"
                )
                error.set_text("")
                fallback_preview["text"] = ""
                voice_draft.update(base="", draft="", full="")
                set_idle(record_more=True)
                return
            message = str(result.get("error") or "Transcription failed.")
            recording_status.set_text("Audio retained for recovery")
            error.set_text(message)
            fallback_preview["text"] = str(result.get("preview") or "").strip()
            use_preview_btn.visible = bool(fallback_preview["text"]) and not voice_draft["full"]
            use_preview_btn.set_text("Use Live Captions")
            mic.visible = True
            mic.enable()
            stop_btn.visible = False
            cancel_voice_btn.visible = True
            cancel_voice_btn.set_text("Discard Recording")
            submit_btn.enable()

        async def begin_voice() -> None:
            if voice_active["value"] or submitting["value"]:
                return
            error.set_text("")
            await stop_speaking()
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
            voice_active["value"] = True
            recording_panel.visible = True
            recording_status.set_text("Recording 00:00 · pauses are safe")
            mic.visible = False
            stop_btn.visible = True
            stop_btn.enable()
            cancel_voice_btn.visible = True
            cancel_voice_btn.set_text("Cancel")

        async def finish_voice() -> None:
            if not voice_active["value"]:
                return
            voice_active["value"] = False
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
                use_preview_btn.visible = False
                mic.visible = False
                stop_btn.visible = False
                cancel_voice_btn.visible = True
                cancel_voice_btn.set_text("Discard Audio")
                submit_btn.enable()
            else:
                handle_transcription(result)
            cancel_voice_btn.enable()

        async def discard_voice() -> None:
            await cancel_recording()
            voice_active["value"] = False
            fallback_preview["text"] = ""
            use_preview_btn.visible = False
            recording_status.set_text("Recording discarded")
            error.set_text("")
            set_idle()

        def use_preview() -> None:
            if fallback_preview["text"]:
                append_transcript(fallback_preview["text"])
                use_preview_btn.visible = False
                recording_status.set_text("Live captions inserted · audio remains available")
            submit_btn.enable()

        async def submit() -> None:
            if submitting["value"]:
                return
            if voice_active["value"]:
                error.set_text("Stop the recording before submitting your answer.")
                return
            text = (answer.value or "").strip()
            if not text:
                error.set_text("Answer the question, or say plainly that you do not know.")
                return
            submitting["value"] = True
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
                await stop_speaking()
                await cancel_recording()
                refresh()
            except Exception as exc:
                error.set_text(f"Could not continue: {exc}")
                submitting["value"] = False
                submit_btn.enable()
                mic.enable()
                submit_btn.set_text("Submit Answer")

        with ui.element("div").classes("interview-feedback") as tips_panel:
            ui.label("DRAFT TIPS").classes("interview-kicker")
            tips_text = ui.label("").style(
                "color:var(--text-muted);font-size:.8rem;line-height:1.55;white-space:pre-wrap;margin-top:.35rem;"
            )
            ui.label(
                "Tips are not a score and are not saved. Your stored Views are optional secondary context and may be stale."
            ).classes("interview-meta").style("margin-top:.45rem;")
            ui.button("Revise Answer", icon="edit", on_click=lambda: answer.run_method("focus")).props(
                "flat dense no-caps"
            ).style("color:var(--accent);font-size:.72rem;margin-top:.35rem;")
        tips_panel.visible = False

        async def get_tips() -> None:
            if tips_loading["value"] or submitting["value"]:
                return
            text = (answer.value or "").strip()
            if not text:
                error.set_text("Write a draft first, then request tips.")
                answer.run_method("focus")
                return
            if voice_active["value"]:
                error.set_text("Stop the recording before requesting tips.")
                return
            tips_loading["value"] = True
            tips_btn.disable()
            tips_btn.set_text("Reviewing Draft…")
            error.set_text("")
            try:
                tips = await run.io_bound(lambda: answer_tips(session.id, text))
                tips_text.set_text(tips)
                tips_panel.visible = True
                answer.run_method("focus")
            except Exception as exc:
                error.set_text(f"Could not get tips: {exc}")
            finally:
                tips_loading["value"] = False
                tips_btn.enable()
                tips_btn.set_text("Get Answer Tips")

        with ui.row().style("gap:0.65rem; align-items:center; margin-top:0.8rem; flex-wrap:wrap;"):
            submit_btn = ui.button("Submit Answer", on_click=submit).classes("submit-btn")
            tips_btn = ui.button("Get Answer Tips", icon="tips_and_updates", on_click=get_tips).classes("cancel-btn")
            mic = ui.button("Speak Answer", icon="mic", on_click=begin_voice).classes("cancel-btn")
            stop_btn = ui.button("Stop & Use Live Draft", icon="stop", on_click=finish_voice).classes("submit-btn")
            cancel_voice_btn = ui.button("Cancel", on_click=discard_voice).classes("cancel-btn")
            use_preview_btn = ui.button("Use Live Captions", on_click=use_preview).classes("cancel-btn")
            stop_btn.visible = False
            cancel_voice_btn.visible = False
            use_preview_btn.visible = False
            ui.label("Voice drafts stay editable. Get Answer Tips gives coaching before you submit.").classes("interview-meta")
        ui.label(
            "SHORTCUTS · Ctrl/Cmd+Enter submit · Alt+M start/stop voice"
        ).classes("interview-shortcuts").style("margin-top:0.55rem;")

        async def handle_shortcut(event) -> None:
            if not event.action.keydown or event.action.repeat:
                return
            if event.key.enter and (event.modifiers.ctrl or event.modifiers.meta):
                await submit()
            elif event.key.name.lower() == "m" and event.modifiers.alt:
                if voice_active["value"]:
                    await finish_voice()
                else:
                    await begin_voice()

        # Deliberately include textarea focus: Ctrl/Cmd+Enter is a submit chord,
        # while ordinary Enter and Space remain safe for writing an answer.
        ui.keyboard(handle_shortcut, repeating=False, ignore=[])
        ui.timer(0.1, lambda: answer.run_method("focus"), once=True)


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

    advancing = {"value": False}

    async def next_question() -> None:
        if advancing["value"]:
            return
        advancing["value"] = True
        try:
            state["session"] = await run.io_bound(lambda: advance_session(session.id, result))
            state["pending"] = None
            state["retrying"] = False
            refresh()
        except Exception as exc:
            advancing["value"] = False
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
    ui.label("SHORTCUTS · Ctrl/Cmd+Enter next question").classes(
        "interview-shortcuts"
    ).style("margin-top:0.55rem;")

    async def handle_shortcut(event) -> None:
        if not event.action.keydown or event.action.repeat:
            return
        if event.key.enter and (event.modifiers.ctrl or event.modifiers.meta):
            await next_question()

    ui.keyboard(handle_shortcut, repeating=False, ignore=[])


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

    if session.model_note_ids:
        mode = _MODEL_PRESET_MODES.get(session.preset_key, "")
        if mode:
            pm_status = ui.label("").style("color:#f87171; font-size:.75rem; min-height:1rem; margin-top:.4rem;")

            def back_to_library() -> None:
                state.update(
                    session=None, pending=None, retrying=False,
                    models_setup={"mode": mode},
                    quant_session_note=session.model_note_ids[0],
                    compare_sel=list(session.model_note_ids[:2]),
                )
                refresh()

            def resolve_notes() -> list[ModelNote] | None:
                try:
                    scanned = {note.id: note for note in scan_model_notes()}
                    return [scanned[note_id] for note_id in session.model_note_ids]
                except Exception:
                    return None

            with ui.row().style("gap:.55rem;flex-wrap:wrap;margin-top:.5rem;"):
                again_btn = ui.button("Try Again").classes("submit-btn")

                async def retry_again(_, target=again_btn) -> None:
                    picked = resolve_notes()
                    if not picked or (mode == "compare" and len(picked) < 2):
                        back_to_library()
                        return
                    if mode == "compare":
                        topic = f"{picked[0].title} vs {picked[1].title}"
                        opener = _compare_opener(picked[0], picked[1])
                    else:
                        topic = picked[0].title
                        opener = _model_opener(mode, picked[0].title)
                    await _start_model_session(
                        state, refresh,
                        preset_key=preset.key, topic=topic, initial_question=opener,
                        notes=picked, style=session.practice_style or _MODEL_MODE_LABELS[mode],
                        target_questions=preset.default_questions,
                        button=target, status=pm_status, button_label="Try Again",
                    )

                again_btn.on("click", retry_again)
                if mode != "compare" and len(session.model_note_ids) == 1:
                    for other_mode in _MODEL_ROW_MODES:
                        if other_mode == mode:
                            continue
                        switch_btn = ui.button(_MODEL_MODE_LABELS[other_mode]).classes("cancel-btn")

                        async def switch_mode(_, target=switch_btn, variant=other_mode) -> None:
                            picked = resolve_notes()
                            if not picked:
                                back_to_library()
                                return
                            other_preset = get_preset(f"model_{variant}")
                            await _start_model_session(
                                state, refresh,
                                preset_key=other_preset.key, topic=picked[0].title,
                                initial_question=_model_opener(variant, picked[0].title),
                                notes=picked, style=_MODEL_MODE_LABELS[variant],
                                target_questions=other_preset.default_questions,
                                button=target, status=pm_status,
                                button_label=_MODEL_MODE_LABELS[variant],
                            )

                        switch_btn.on("click", switch_mode)


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
