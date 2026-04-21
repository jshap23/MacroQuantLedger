from __future__ import annotations
from datetime import datetime, timezone
from nicegui import ui
from models.schema import AppState, Project, Skill, ReadinessItem
from storage.persistence import save_state
from components.status_bar import days_since, staleness_color, staleness_label


def touch_now():
    return datetime.now(tz=timezone.utc)


PRIORITY_COLORS = {
    "High":   {"bg": "#6b1a1a", "text": "#f87171"},
    "Medium": {"bg": "#4a3a0a", "text": "#fbbf24"},
    "Low":    {"bg": "#1a3a2a", "text": "#4ade80"},
    "—":      {"bg": "#1e1e24", "text": "#555566"},
}

LEVEL_COLORS = {
    "Strong":   {"bg": "#0d2e2b", "text": "#2dd4bf"},
    "Working":  {"bg": "#1a2a40", "text": "#60a5fa"},
    "Beginner": {"bg": "#2a2a38", "text": "#a0a0b8"},
    "—":        {"bg": "#1e1e24", "text": "#555566"},
}

RELEVANCE_COLORS = {
    "High":   {"bg": "#0d2e2b", "text": "#2dd4bf"},
    "Medium": {"bg": "#2a2a38", "text": "#a0a0b8"},
    "Low":    {"bg": "#1e1e24", "text": "#555566"},
    "—":      {"bg": "#1e1e24", "text": "#444455"},
}

STRENGTH_COLORS = {
    "Strength": {"bg": "#1a3a2a", "text": "#4ade80"},
    "Mixed":    {"bg": "#4a3a0a", "text": "#fbbf24"},
    "Gap":      {"bg": "#6b1a1a", "text": "#f87171"},
    "":         {"bg": "#1e1e24", "text": "#555566"},
}

_CSS_INJECTED = False


def _inject_css():
    global _CSS_INJECTED
    if _CSS_INJECTED:
        return
    _CSS_INJECTED = True
    ui.add_css("""
        .qt-section-label {
            font-size: 0.59rem;
            font-weight: 700;
            color: var(--text-faint);
            letter-spacing: 0.14em;
            font-family: 'IBM Plex Mono', monospace;
        }
        .qt-grid-proj {
            display: grid;
            grid-template-columns: 1fr 80px 1fr 66px 18px;
            gap: 0 0.7rem;
            padding: 0.5rem 0.75rem;
            align-items: center;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            cursor: pointer;
            transition: border-color 0.12s, background 0.12s;
        }
        .qt-grid-proj:hover {
            border-color: var(--border-strong);
            background: var(--bg-hover);
        }
        .qt-grid-skill {
            display: grid;
            grid-template-columns: 1fr 100px 90px 1fr 18px;
            gap: 0 0.7rem;
            padding: 0.5rem 0.75rem;
            align-items: center;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            cursor: pointer;
            transition: border-color 0.12s, background 0.12s;
        }
        .qt-grid-skill:hover {
            border-color: var(--border-strong);
            background: var(--bg-hover);
        }
        .qt-grid-ready {
            display: grid;
            grid-template-columns: 1fr 90px 1fr 66px 18px;
            gap: 0 0.7rem;
            padding: 0.5rem 0.75rem;
            align-items: center;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            cursor: pointer;
            transition: border-color 0.12s, background 0.12s;
        }
        .qt-grid-ready:hover {
            border-color: var(--border-strong);
            background: var(--bg-hover);
        }
        .qt-col-header-proj {
            display: grid;
            grid-template-columns: 1fr 80px 1fr 66px 18px;
            gap: 0 0.7rem;
            padding: 0 0.75rem 0.35rem;
            align-items: center;
        }
        .qt-col-header-skill {
            display: grid;
            grid-template-columns: 1fr 100px 90px 1fr 18px;
            gap: 0 0.7rem;
            padding: 0 0.75rem 0.35rem;
            align-items: center;
        }
        .qt-col-header-ready {
            display: grid;
            grid-template-columns: 1fr 90px 1fr 66px 18px;
            gap: 0 0.7rem;
            padding: 0 0.75rem 0.35rem;
            align-items: center;
        }
        .qt-drawer-card {
            width: min(460px, 95vw);
            height: 100vh;
            background: var(--bg-card);
            color: var(--text-primary);
            border-left: 1px solid var(--border-strong);
            border-radius: 0;
            padding: 0;
            margin: 0;
            overflow-y: auto;
            box-shadow: -4px 0 24px rgba(0,0,0,0.35);
        }
        body.light-mode .qt-drawer-card {
            box-shadow: -4px 0 24px rgba(0,0,0,0.12);
        }
    """)


def _badge(color_map: dict, value: str) -> None:
    c = color_map.get(value, color_map.get("—", color_map.get("", {"bg": "#1e1e24", "text": "#555566"})))
    label = value if value else "—"
    ui.element("span").style(
        f"background:{c['bg']};color:{c['text']};padding:2px 7px;border-radius:4px;"
        f"font-size:0.67rem;font-weight:700;letter-spacing:0.04em;"
        f"border:1px solid {c['text']}33;white-space:nowrap;"
    ).text = label


def _preview(text: str, placeholder: str = "—") -> None:
    if text and text.strip():
        ui.label(text).style(
            "font-size:0.78rem;color:var(--text-muted);overflow:hidden;"
            "text-overflow:ellipsis;white-space:nowrap;"
        )
    else:
        ui.label(placeholder).style("font-size:0.78rem;color:var(--text-faint);")


def _arrow() -> None:
    ui.label("›").style("color:var(--text-faint);font-size:1rem;text-align:center;line-height:1;")


def _drawer_header(title: str, subtitle: str, dialog) -> None:
    with ui.row().style(
        "width:100%;align-items:center;justify-content:space-between;"
        "margin-bottom:1.5rem;border-bottom:1px solid var(--border);padding-bottom:1rem;"
    ):
        with ui.column().style("gap:2px;"):
            ui.label(subtitle).style(
                "font-size:0.6rem;font-weight:700;color:var(--text-faint);letter-spacing:0.14em;"
            )
            ui.label(title or "Untitled").style(
                "font-size:1rem;font-weight:700;color:var(--accent);letter-spacing:0.06em;"
            )
        ui.button("✕", on_click=dialog.close).style(
            "background:transparent;color:var(--text-muted);box-shadow:none;"
            "min-width:unset;padding:0 0.5rem;font-size:1rem;line-height:1;"
        )


def render_quant_tracker(state: AppState, save_indicator):
    _inject_css()

    def save():
        save_state(state)
        save_indicator()

    # Single shared drawer for all three sections
    with ui.dialog().props('position="right" full-height').style(
        "font-family:'IBM Plex Mono',monospace;"
    ) as drawer:
        with ui.element("div").classes("qt-drawer-card"):
            drawer_body = ui.column().style("width:100%;gap:0;padding:1.25rem 1.25rem 2rem;")

    def open_drawer(render_fn):
        drawer_body.clear()
        with drawer_body:
            render_fn()
        drawer.open()

    _render_projects(state, save, drawer, drawer_body, open_drawer)
    _render_skills(state, save, drawer, drawer_body, open_drawer)
    _render_readiness(state, save, drawer, drawer_body, open_drawer)


# ── PROJECTS ──────────────────────────────────────────────────────────────────

def _proj_row_contents(proj: Project) -> None:
    name = proj.name or "Untitled project"
    ui.label(name).style(
        "font-weight:600;font-size:0.85rem;overflow:hidden;"
        "text-overflow:ellipsis;white-space:nowrap;"
    )
    _badge(PRIORITY_COLORS, proj.priority)
    _preview(proj.status, "no status")
    d = days_since(proj.last_touched)
    ui.label(staleness_label(d)).style(
        f"color:{staleness_color(d)};font-size:0.71rem;white-space:nowrap;text-align:right;"
    )
    _arrow()


def _render_projects(state, save, drawer, drawer_body, open_drawer):
    ui.label("ACTIVE RESEARCH PROJECTS").classes("section-header")

    with ui.element("div").classes("qt-col-header-proj"):
        for lbl in ["PROJECT", "PRIORITY", "STATUS", "UPDATED", ""]:
            ui.label(lbl).classes("qt-section-label")

    row_containers: dict[str, ui.element] = {}
    rows_col = ui.column().style("width:100%;gap:0.3rem;")

    def refresh_row(proj: Project):
        el = row_containers.get(proj.id)
        if el:
            el.clear()
            with el:
                _proj_row_contents(proj)

    def add_project():
        p = Project()
        state.quant_tracker.projects.append(p)
        save()
        row_el = ui.element("div").classes("qt-grid-proj")
        row_containers[p.id] = row_el
        with rows_col:
            with row_el:
                _proj_row_contents(p)
            row_el.on("click", lambda _, proj=p: open_drawer(
                lambda proj=proj: _proj_drawer(proj, state, save, refresh_row, lambda proj=proj: _remove_proj(proj, state, save, rows_col, row_containers, drawer), drawer)
            ))
        open_drawer(lambda proj=p: _proj_drawer(proj, state, save, refresh_row, lambda proj=p: _remove_proj(proj, state, save, rows_col, row_containers, drawer), drawer))

    with rows_col:
        for proj in state.quant_tracker.projects:
            row_el = ui.element("div").classes("qt-grid-proj")
            row_containers[proj.id] = row_el
            with row_el:
                _proj_row_contents(proj)
            row_el.on("click", lambda _, p=proj: open_drawer(
                lambda p=p: _proj_drawer(p, state, save, refresh_row, lambda p=p: _remove_proj(p, state, save, rows_col, row_containers, drawer), drawer)
            ))

    ui.button("+ Add project", on_click=add_project).classes("add-btn").style("margin-top:0.5rem;")


def _remove_proj(proj, state, save, rows_col, row_containers, drawer):
    drawer.close()
    try:
        state.quant_tracker.projects.remove(proj)
    except ValueError:
        pass
    el = row_containers.pop(proj.id, None)
    if el:
        rows_col.remove(el)
    save()


def _proj_drawer(proj: Project, state, save, refresh_row, on_remove, dialog):
    def update():
        proj.last_touched = touch_now()
        save()
        refresh_row(proj)

    _drawer_header(proj.name or "Untitled project", "RESEARCH PROJECT", dialog)

    ui.label("PROJECT NAME").classes("field-label")
    name_in = ui.input(value=proj.name, placeholder="Project name…").classes("w-full dark-input")
    name_in.on("blur", lambda _, p=proj, ni=name_in: (setattr(p, "name", ni.value), update()))

    ui.label("PRIORITY").classes("field-label").style("margin-top:0.75rem;")
    ui.select(
        ["—", "High", "Medium", "Low"], value=proj.priority,
        on_change=lambda e, p=proj: (setattr(p, "priority", e.value), update())
    ).classes("w-full dark-input")

    ui.label("STATUS").classes("field-label").style("margin-top:0.75rem;")
    status_in = ui.textarea(
        value=proj.status, placeholder="What's working, what's stuck…"
    ).classes("w-full dark-input")
    status_in.on("blur", lambda _, p=proj, si=status_in: (setattr(p, "status", si.value), update()))

    ui.label("NEXT STEP").classes("field-label").style("margin-top:0.75rem;")
    next_in = ui.input(
        value=proj.next_step, placeholder="Next concrete deliverable…"
    ).classes("w-full dark-input")
    next_in.on("blur", lambda _, p=proj, ni=next_in: (setattr(p, "next_step", ni.value), update()))

    ui.button("Remove project", on_click=on_remove).style(
        "margin-top:2rem;background:transparent;color:#f87171;"
        "border:1px solid #f8717133;box-shadow:none;font-size:0.75rem;"
        "font-family:'IBM Plex Mono',monospace;border-radius:4px;"
    )


# ── SKILLS ────────────────────────────────────────────────────────────────────

def _skill_row_contents(skill: Skill) -> None:
    name = skill.name or "Untitled skill"
    ui.label(name).style(
        "font-weight:600;font-size:0.85rem;overflow:hidden;"
        "text-overflow:ellipsis;white-space:nowrap;"
    )
    _badge(LEVEL_COLORS, skill.level)
    _badge(RELEVANCE_COLORS, skill.interview_relevance)
    _preview(skill.building, "no activity")
    _arrow()


def _render_skills(state, save, drawer, drawer_body, open_drawer):
    ui.label("TECHNICAL SKILLS INVENTORY").classes("section-header").style("margin-top:2rem;")

    with ui.element("div").classes("qt-col-header-skill"):
        for lbl in ["SKILL", "LEVEL", "INTERVIEW REL.", "BUILDING", ""]:
            ui.label(lbl).classes("qt-section-label")

    row_containers: dict[str, ui.element] = {}
    rows_col = ui.column().style("width:100%;gap:0.3rem;")

    def refresh_row(skill: Skill):
        el = row_containers.get(skill.id)
        if el:
            el.clear()
            with el:
                _skill_row_contents(skill)

    def add_skill():
        s = Skill()
        state.quant_tracker.skills.append(s)
        save()
        row_el = ui.element("div").classes("qt-grid-skill")
        row_containers[s.id] = row_el
        with rows_col:
            with row_el:
                _skill_row_contents(s)
            row_el.on("click", lambda _, skill=s: open_drawer(
                lambda skill=skill: _skill_drawer(skill, state, save, refresh_row, lambda skill=skill: _remove_skill(skill, state, save, rows_col, row_containers, drawer), dialog=drawer)
            ))
        open_drawer(lambda skill=s: _skill_drawer(skill, state, save, refresh_row, lambda skill=s: _remove_skill(skill, state, save, rows_col, row_containers, drawer), dialog=drawer))

    with rows_col:
        for skill in state.quant_tracker.skills:
            row_el = ui.element("div").classes("qt-grid-skill")
            row_containers[skill.id] = row_el
            with row_el:
                _skill_row_contents(skill)
            row_el.on("click", lambda _, s=skill: open_drawer(
                lambda s=s: _skill_drawer(s, state, save, refresh_row, lambda s=s: _remove_skill(s, state, save, rows_col, row_containers, drawer), dialog=drawer)
            ))

    ui.button("+ Add skill", on_click=add_skill).classes("add-btn").style("margin-top:0.5rem;")


def _remove_skill(skill, state, save, rows_col, row_containers, drawer):
    drawer.close()
    try:
        state.quant_tracker.skills.remove(skill)
    except ValueError:
        pass
    el = row_containers.pop(skill.id, None)
    if el:
        rows_col.remove(el)
    save()


def _skill_drawer(skill: Skill, state, save, refresh_row, on_remove, dialog):
    def update():
        skill.last_touched = touch_now()
        save()
        refresh_row(skill)

    _drawer_header(skill.name or "Untitled skill", "TECHNICAL SKILL", dialog)

    ui.label("SKILL / METHOD").classes("field-label")
    name_in = ui.input(value=skill.name, placeholder="Skill or method…").classes("w-full dark-input")
    name_in.on("blur", lambda _, s=skill, ni=name_in: (setattr(s, "name", ni.value), update()))

    ui.label("LEVEL").classes("field-label").style("margin-top:0.75rem;")
    ui.select(
        ["—", "Beginner", "Working", "Strong"], value=skill.level,
        on_change=lambda e, s=skill: (setattr(s, "level", e.value), update())
    ).classes("w-full dark-input")

    ui.label("INTERVIEW RELEVANCE").classes("field-label").style("margin-top:0.75rem;")
    ui.select(
        ["—", "High", "Medium", "Low"], value=skill.interview_relevance,
        on_change=lambda e, s=skill: (setattr(s, "interview_relevance", e.value), update())
    ).classes("w-full dark-input")

    ui.label("BUILDING VIA").classes("field-label").style("margin-top:0.75rem;")
    build_in = ui.input(
        value=skill.building, placeholder="Paper, codebase, course…"
    ).classes("w-full dark-input")
    build_in.on("blur", lambda _, s=skill, bi=build_in: (setattr(s, "building", bi.value), update()))

    ui.button("Remove skill", on_click=on_remove).style(
        "margin-top:2rem;background:transparent;color:#f87171;"
        "border:1px solid #f8717133;box-shadow:none;font-size:0.75rem;"
        "font-family:'IBM Plex Mono',monospace;border-radius:4px;"
    )


# ── READINESS ─────────────────────────────────────────────────────────────────

def _ready_row_contents(item: ReadinessItem) -> None:
    area = item.area or "Untitled topic"
    ui.label(area).style(
        "font-weight:600;font-size:0.85rem;overflow:hidden;"
        "text-overflow:ellipsis;white-space:nowrap;"
    )
    _badge(STRENGTH_COLORS, item.strength)
    _preview(item.evidence, "no evidence")
    d = days_since(item.last_touched)
    ui.label(staleness_label(d)).style(
        f"color:{staleness_color(d)};font-size:0.71rem;white-space:nowrap;text-align:right;"
    )
    _arrow()


def _render_readiness(state, save, drawer, drawer_body, open_drawer):
    ui.label("INTERVIEW READINESS").classes("section-header").style("margin-top:2rem;")

    with ui.element("div").classes("qt-col-header-ready"):
        for lbl in ["TOPIC AREA", "STANDING", "EVIDENCE", "UPDATED", ""]:
            ui.label(lbl).classes("qt-section-label")

    row_containers: dict[str, ui.element] = {}
    rows_col = ui.column().style("width:100%;gap:0.3rem;")

    def refresh_row(item: ReadinessItem):
        el = row_containers.get(item.id)
        if el:
            el.clear()
            with el:
                _ready_row_contents(item)

    def add_item():
        it = ReadinessItem()
        state.quant_tracker.readiness.append(it)
        save()
        row_el = ui.element("div").classes("qt-grid-ready")
        row_containers[it.id] = row_el
        with rows_col:
            with row_el:
                _ready_row_contents(it)
            row_el.on("click", lambda _, item=it: open_drawer(
                lambda item=item: _ready_drawer(item, state, save, refresh_row, lambda item=item: _remove_ready(item, state, save, rows_col, row_containers, drawer), dialog=drawer)
            ))
        open_drawer(lambda item=it: _ready_drawer(it, state, save, refresh_row, lambda item=it: _remove_ready(it, state, save, rows_col, row_containers, drawer), dialog=drawer))

    with rows_col:
        for item in state.quant_tracker.readiness:
            row_el = ui.element("div").classes("qt-grid-ready")
            row_containers[item.id] = row_el
            with row_el:
                _ready_row_contents(item)
            row_el.on("click", lambda _, it=item: open_drawer(
                lambda it=it: _ready_drawer(it, state, save, refresh_row, lambda it=it: _remove_ready(it, state, save, rows_col, row_containers, drawer), dialog=drawer)
            ))

    ui.button("+ Add topic", on_click=add_item).classes("add-btn").style("margin-top:0.5rem;")


def _remove_ready(item, state, save, rows_col, row_containers, drawer):
    drawer.close()
    try:
        state.quant_tracker.readiness.remove(item)
    except ValueError:
        pass
    el = row_containers.pop(item.id, None)
    if el:
        rows_col.remove(el)
    save()


def _ready_drawer(item: ReadinessItem, state, save, refresh_row, on_remove, dialog):
    def update():
        item.last_touched = touch_now()
        save()
        refresh_row(item)

    _drawer_header(item.area or "Untitled topic", "READINESS TOPIC", dialog)

    ui.label("TOPIC AREA").classes("field-label")
    area_in = ui.input(value=item.area, placeholder="Topic area…").classes("w-full dark-input")
    area_in.on("blur", lambda _, it=item, ai=area_in: (setattr(it, "area", ai.value), update()))

    ui.label("STANDING").classes("field-label").style("margin-top:0.75rem;")
    ui.select(
        ["", "Strength", "Mixed", "Gap"], value=item.strength,
        on_change=lambda e, it=item: (setattr(it, "strength", e.value), update())
    ).classes("w-full dark-input")

    ui.label("EVIDENCE").classes("field-label").style("margin-top:0.75rem;")
    ev_in = ui.textarea(
        value=item.evidence, placeholder="Can you demo this? What proves it?"
    ).classes("w-full dark-input")
    ev_in.on("blur", lambda _, it=item, ei=ev_in: (setattr(it, "evidence", ei.value), update()))

    ui.label("ACTION THIS WEEK").classes("field-label").style("margin-top:0.75rem;")
    act_in = ui.input(
        value=item.action, placeholder="One concrete thing to move this forward…"
    ).classes("w-full dark-input")
    act_in.on("blur", lambda _, it=item, ai=act_in: (setattr(it, "action", ai.value), update()))

    ui.button("Remove topic", on_click=on_remove).style(
        "margin-top:2rem;background:transparent;color:#f87171;"
        "border:1px solid #f8717133;box-shadow:none;font-size:0.75rem;"
        "font-family:'IBM Plex Mono',monospace;border-radius:4px;"
    )
