from __future__ import annotations
from datetime import datetime, timezone
from nicegui import ui
from models.schema import AppState, Project, Skill, ReadinessItem
from storage.persistence import save_state
from components.status_bar import days_since, staleness_color, staleness_label


def touch_now():
    return datetime.now(tz=timezone.utc)


def render_quant_tracker(state: AppState, save_indicator):
    def save():
        save_state(state)
        save_indicator()

    _render_projects(state, save)
    _render_skills(state, save)
    _render_readiness(state, save)


# ── PROJECTS ──────────────────────────────────────────────────────────────────

def _render_projects(state: AppState, save):
    ui.label("ACTIVE RESEARCH PROJECTS").classes("section-header")

    container = ui.element("div").classes("quant-section-container")

    def refresh():
        container.clear()
        with container:
            for proj in list(state.quant_tracker.projects):
                _project_card(proj, state, save, refresh)
            with ui.element("div").style("margin-top:0.5rem;"):
                ui.button("+ Add project", on_click=lambda: _add_project(state, save, refresh)) \
                    .classes("add-btn")

    refresh()


def _add_project(state: AppState, save, refresh):
    state.quant_tracker.projects.append(Project())
    save()
    refresh()


def _project_card(proj: Project, state: AppState, save, refresh):
    with ui.element("div").classes("quant-card"):
        # Row 1
        with ui.row().classes("quant-card-row").style("align-items:center; gap:0.5rem;"):
            name_in = ui.input(value=proj.name, placeholder="Project name…").classes("dark-input").style("flex:1;")
            name_in.on("blur", lambda _, p=proj, ni=name_in: (
                setattr(p, "name", ni.value),
                setattr(p, "last_touched", touch_now()),
                save()
            ))

            pri_sel = ui.select(
                ["—", "High", "Medium", "Low"], value=proj.priority,
                on_change=lambda e, p=proj: (
                    setattr(p, "priority", e.value),
                    setattr(p, "last_touched", touch_now()),
                    save()
                )
            ).classes("dark-input").style("width:120px;")

            d = days_since(proj.last_touched)
            ui.label(staleness_label(d)).style(f"color:{staleness_color(d)}; font-size:0.8rem; min-width:70px; text-align:right;")

            ui.button("✕", on_click=lambda _, p=proj: _remove_item(state.quant_tracker.projects, p, save, refresh)) \
                .classes("remove-btn")

        # Row 2
        status_in = ui.textarea(value=proj.status, placeholder="What's working, what's stuck…").classes("full-width dark-input")
        status_in.on("blur", lambda _, p=proj, si=status_in: (
            setattr(p, "status", si.value),
            setattr(p, "last_touched", touch_now()),
            save()
        ))

        # Row 3
        next_in = ui.input(value=proj.next_step, placeholder="Next concrete deliverable…").classes("full-width dark-input")
        next_in.on("blur", lambda _, p=proj, ni=next_in: (
            setattr(p, "next_step", ni.value),
            setattr(p, "last_touched", touch_now()),
            save()
        ))


# ── SKILLS ────────────────────────────────────────────────────────────────────

def _render_skills(state: AppState, save):
    ui.label("TECHNICAL SKILLS INVENTORY").classes("section-header").style("margin-top:2rem;")

    container = ui.element("div").classes("quant-section-container")

    def refresh():
        container.clear()
        with container:
            for skill in list(state.quant_tracker.skills):
                _skill_card(skill, state, save, refresh)
            with ui.element("div").style("margin-top:0.5rem;"):
                ui.button("+ Add skill", on_click=lambda: _add_skill(state, save, refresh)) \
                    .classes("add-btn")

    refresh()


def _add_skill(state: AppState, save, refresh):
    state.quant_tracker.skills.append(Skill())
    save()
    refresh()


def _skill_card(skill: Skill, state: AppState, save, refresh):
    with ui.element("div").classes("quant-card"):
        # Row 1
        with ui.row().classes("quant-card-row").style("align-items:center; gap:0.5rem;"):
            name_in = ui.input(value=skill.name, placeholder="Skill or method…").classes("dark-input").style("flex:1;")
            name_in.on("blur", lambda _, s=skill, ni=name_in: (
                setattr(s, "name", ni.value),
                setattr(s, "last_touched", touch_now()),
                save()
            ))

            ui.select(
                ["—", "Beginner", "Working", "Strong"], value=skill.level,
                on_change=lambda e, s=skill: (
                    setattr(s, "level", e.value),
                    setattr(s, "last_touched", touch_now()),
                    save()
                )
            ).classes("dark-input").style("width:130px;")

            ui.select(
                ["—", "High", "Medium", "Low"], value=skill.interview_relevance,
                on_change=lambda e, s=skill: (
                    setattr(s, "interview_relevance", e.value),
                    setattr(s, "last_touched", touch_now()),
                    save()
                )
            ).classes("dark-input").style("width:120px;")

            ui.button("✕", on_click=lambda _, s=skill: _remove_item(state.quant_tracker.skills, s, save, refresh)) \
                .classes("remove-btn")

        # Row 2
        build_in = ui.input(value=skill.building, placeholder="Paper, codebase, course…").classes("full-width dark-input")
        build_in.on("blur", lambda _, s=skill, bi=build_in: (
            setattr(s, "building", bi.value),
            setattr(s, "last_touched", touch_now()),
            save()
        ))


# ── READINESS ─────────────────────────────────────────────────────────────────

def _render_readiness(state: AppState, save):
    ui.label("INTERVIEW READINESS").classes("section-header").style("margin-top:2rem;")

    container = ui.element("div").classes("quant-section-container")

    def refresh():
        container.clear()
        with container:
            for item in list(state.quant_tracker.readiness):
                _readiness_card(item, state, save, refresh)
            with ui.element("div").style("margin-top:0.5rem;"):
                ui.button("+ Add topic", on_click=lambda: _add_readiness(state, save, refresh)) \
                    .classes("add-btn")

    refresh()


def _add_readiness(state: AppState, save, refresh):
    state.quant_tracker.readiness.append(ReadinessItem())
    save()
    refresh()


def _readiness_card(item: ReadinessItem, state: AppState, save, refresh):
    with ui.element("div").classes("quant-card"):
        # Row 1
        with ui.row().classes("quant-card-row").style("align-items:center; gap:0.5rem;"):
            area_in = ui.input(value=item.area, placeholder="Topic area…").classes("dark-input").style("flex:1;")
            area_in.on("blur", lambda _, it=item, ai=area_in: (
                setattr(it, "area", ai.value),
                setattr(it, "last_touched", touch_now()),
                save()
            ))

            ui.select(
                ["", "Strength", "Gap", "Mixed"], value=item.strength,
                on_change=lambda e, it=item: (
                    setattr(it, "strength", e.value),
                    setattr(it, "last_touched", touch_now()),
                    save()
                )
            ).classes("dark-input").style("width:130px;")

            d = days_since(item.last_touched)
            ui.label(staleness_label(d)).style(f"color:{staleness_color(d)}; font-size:0.8rem; min-width:70px; text-align:right;")

            ui.button("✕", on_click=lambda _, it=item: _remove_item(state.quant_tracker.readiness, it, save, refresh)) \
                .classes("remove-btn")

        # Row 2
        with ui.row().style("gap:0.75rem;"):
            ev_in = ui.input(value=item.evidence, placeholder="Evidence — can you demo this?").classes("dark-input").style("flex:1;")
            ev_in.on("blur", lambda _, it=item, ei=ev_in: (
                setattr(it, "evidence", ei.value),
                setattr(it, "last_touched", touch_now()),
                save()
            ))

            act_in = ui.input(value=item.action, placeholder="Action this week…").classes("dark-input").style("flex:1;")
            act_in.on("blur", lambda _, it=item, ai=act_in: (
                setattr(it, "action", ai.value),
                setattr(it, "last_touched", touch_now()),
                save()
            ))


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _remove_item(lst: list, item, save, refresh):
    try:
        lst.remove(item)
    except ValueError:
        pass
    save()
    refresh()
