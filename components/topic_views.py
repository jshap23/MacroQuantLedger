"""Living rolodex for developing, arranging, and practicing structured Views."""
from __future__ import annotations

from datetime import datetime, timezone

from nicegui import run, ui

from models.schema import AppState, TopicView, ViewFact, ViewPoint
from services.interview_llm import available as llm_available
from services.topic_views import challenge_view, improve_flow, structure_notes, touch
from storage.persistence import save_state
from storage.topic_view_sync import resolve_conflict, sync_is_enabled, sync_topic_views
from storage.user_settings import obsidian_views_folder


def _inject_css() -> None:
    ui.add_head_html('''<style id="mq-topic-views-css">
      .tv-shell{width:100%;max-width:1120px;margin:0 auto}.tv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(285px,1fr));gap:.8rem;width:100%}
      .tv-card,.tv-section{background:var(--bg-card);border:1px solid var(--border-strong);border-radius:7px;padding:1rem}.tv-card{cursor:pointer;transition:border-color .15s,transform .15s}.tv-card:hover{border-color:var(--accent);transform:translateY(-1px)}
      .tv-name{font-weight:700;font-size:.94rem;color:var(--text-primary)}.tv-bottom{color:var(--text-muted);font-size:.77rem;line-height:1.5;min-height:2.3rem;margin:.45rem 0}.tv-meta{font:500 .64rem 'IBM Plex Mono',monospace;color:var(--text-faint)}
      .tv-pill{display:inline-block;border:1px solid var(--border-strong);border-radius:99px;padding:2px 7px;font:600 .6rem 'IBM Plex Mono',monospace;color:var(--text-muted)}
      .tv-card-tag{display:inline-block;border:1px solid var(--border);border-radius:99px;padding:2px 7px;font:500 .6rem 'IBM Plex Mono',monospace;color:var(--text-muted);background:var(--bg-input)}
      .tv-filter-chip{padding:.18rem .55rem !important;border-radius:99px !important;font:600 .65rem 'IBM Plex Mono',monospace !important;color:var(--text-muted) !important;background:var(--bg-input) !important;border:1px solid var(--border) !important;box-shadow:none !important;text-transform:none !important;min-height:unset !important}
      .tv-filter-chip:hover{border-color:var(--border-strong) !important;color:var(--text-primary) !important}
      .q-btn.q-btn--standard.q-btn--rectangle.tv-filter-chip.is-active{color:#1a1a1a !important;border-color:#f59e0b !important;background:#f59e0b !important}
      .q-btn.q-btn--standard.q-btn--rectangle.tv-filter-chip.is-active .q-btn__content{color:#1a1a1a !important}
      .q-btn.q-btn--standard.q-btn--rectangle.tv-filter-chip.is-active:hover{color:#1a1a1a !important;border-color:#fbbf24 !important;background:#fbbf24 !important}
      .q-btn.q-btn--standard.q-btn--rectangle.tv-filter-chip.is-active:hover .q-btn__content{color:#1a1a1a !important}
      body.light-mode .q-btn.q-btn--standard.q-btn--rectangle.tv-filter-chip.is-active{color:#ffffff !important;border-color:#b45309 !important;background:#b45309 !important}
      body.light-mode .q-btn.q-btn--standard.q-btn--rectangle.tv-filter-chip.is-active .q-btn__content{color:#ffffff !important}
      body.light-mode .q-btn.q-btn--standard.q-btn--rectangle.tv-filter-chip.is-active:hover{color:#ffffff !important;border-color:#92400e !important;background:#92400e !important}
      body.light-mode .q-btn.q-btn--standard.q-btn--rectangle.tv-filter-chip.is-active:hover .q-btn__content{color:#ffffff !important}
      .tv-filter-clear{color:var(--text-faint) !important;font-size:.65rem !important;text-transform:none !important;min-height:unset !important}
      .tv-point{background:var(--bg-card);border:1px solid var(--border-strong);border-radius:7px;margin:.75rem 0;padding:.8rem 1rem}.tv-point-head{display:grid;grid-template-columns:34px 1fr auto;align-items:center;gap:.5rem}
      .tv-fact{display:grid;grid-template-columns:28px 1fr auto;align-items:start;gap:.45rem;padding:.38rem 0;border-top:1px solid var(--border)}.tv-handle{color:var(--text-faint);cursor:grab;font:700 1rem 'IBM Plex Mono',monospace;padding-top:.5rem}.tv-actions .q-btn{min-width:28px!important;padding:2px!important}
      .tv-edit textarea{line-height:1.5!important}.tv-ai{border-left:3px solid var(--accent);background:var(--accent-glow);padding:.75rem 1rem;margin:.75rem 0;border-radius:0 6px 6px 0}      .tv-empty{border:1px dashed var(--border-strong);border-radius:7px;padding:2rem;text-align:center;color:var(--text-muted)}
      .tv-sync-bar{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin:.6rem 0 1rem;padding:.55rem .75rem;background:var(--bg-card);border:1px solid var(--border);border-radius:6px}
      .tv-sync-label{font:500 .64rem 'IBM Plex Mono',monospace;color:var(--text-muted)}
      .tv-sync-folder{color:var(--accent);font-weight:700}
      .tv-conflict{background:var(--bg-card);border:1px solid #f8717155;border-left:3px solid #f87171;border-radius:0 6px 6px 0;padding:.75rem 1rem;margin:.75rem 0}
      .tv-conflict-title{font-weight:700;color:#f87171;font-size:.85rem}
      .tv-tag-chips{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin:.3rem 0 .15rem}
      .tv-tag-chip{background:var(--accent-glow)!important;border:1px solid var(--border-strong)!important;color:var(--text-primary)!important;font:600 .68rem 'IBM Plex Mono',monospace!important;border-radius:99px!important;min-height:0!important;padding:.25rem .5rem!important}
      .tv-tag-chip .q-chip__content{padding:0!important;font-weight:600!important;font-size:inherit!important}
      .tv-tag-chip .q-chip__icon--remove{color:var(--text-muted)!important;opacity:.65!important;margin-left:.3rem!important;font-size:.85em!important;cursor:pointer!important}
      .tv-tag-chip .q-chip__icon--remove:hover{opacity:1!important;color:var(--accent)!important}
      .tv-tag-input{max-width:220px}
      .tv-tag-add-btn{color:var(--accent)!important}
      @media(max-width:650px){.tv-point{padding:.7rem}.tv-point-head{grid-template-columns:24px 1fr}.tv-point-head>.tv-actions{grid-column:2}.tv-fact{grid-template-columns:20px 1fr}.tv-fact>.tv-actions{grid-column:2}}
    </style>''')


def _when(value: datetime | None) -> str:
    if not value:
        return "Never"
    # Older/newly-created records may contain local offset-naive timestamps,
    # while practice metadata uses offset-aware UTC timestamps. Compare like
    # with like so existing state files remain valid without a migration.
    now = datetime.now(value.tzinfo) if value.tzinfo is not None else datetime.now()
    days = max(0, (now - value).days)
    return "Today" if days == 0 else f"{days}d ago"


def render_topic_views(state: AppState, save_indicator, practice_view, open_bridge=None) -> None:
    _inject_css()
    local = {"selected": None, "show_archived": False, "ai": [], "conflicts": [], "tag_filter": set()}
    root = ui.element("div").classes("tv-shell")

    def _maybe_sync(silent: bool = False) -> None:
        folder = obsidian_views_folder()
        if not folder or not sync_is_enabled():
            return
        try:
            result = sync_topic_views(state, folder)
            local["conflicts"] = result.conflicts
            if result.imported or result.created:
                save_state(state)
                save_indicator()
            if result.conflicts and not silent:
                ui.notify(f"{len(result.conflicts)} View(s) have sync conflicts.", type="warning")
            elif (result.imported or result.exported or result.created) and not silent:
                ui.notify("Views synced with Obsidian.", type="positive")
            if result.errors and not silent:
                ui.notify("; ".join(result.errors), type="negative")
        except Exception as exc:
            if not silent:
                ui.notify(f"Could not sync Views: {exc}", type="negative")

    def persist(view: TopicView | None = None) -> None:
        if view:
            touch(view)
        save_state(state)
        save_indicator()
        _maybe_sync()

    def refresh() -> None:
        root.clear()
        with root:
            view = next((item for item in state.topic_views if item.id == local["selected"]), None)
            if view:
                _detail(view, state, local, persist, refresh, practice_view)
            else:
                _overview(state, local, persist, refresh)

    if open_bridge is not None:
        open_bridge["open"] = lambda view_id: (local.update(selected=view_id), refresh())

    _maybe_sync(silent=True)
    refresh()


def _sync_bar(state: AppState, local: dict, persist, refresh) -> None:
    folder = obsidian_views_folder()
    enabled = sync_is_enabled()

    def do_sync():
        if not obsidian_views_folder() or not sync_is_enabled():
            ui.notify("Sync is off. Set an Obsidian Views folder and tick 'Enable bidirectional My Views sync' in ··· → Settings.", type="warning", position="top")
            return
        persist()
        refresh()

    with ui.element("div").classes("tv-sync-bar"):
        if not folder:
            ui.label("Obsidian Views folder not configured").classes("tv-sync-label")
        elif not enabled:
            ui.label("Obsidian sync is off").classes("tv-sync-label")
            ui.label(f"folder ready: {folder}").classes("tv-sync-label tv-sync-folder")
        else:
            ui.label("Obsidian folder:").classes("tv-sync-label")
            ui.label(str(folder)).classes("tv-sync-label tv-sync-folder")
        ui.button("Sync Views", icon="sync", on_click=do_sync).props("flat dense no-caps")
        if local.get("conflicts"):
            ui.badge(str(len(local["conflicts"])), color="negative").tooltip("Sync conflicts")
            ui.button("Resolve", on_click=lambda: _conflict_dialog(state, local, persist, refresh)).props("flat dense no-caps color=negative")


def _conflict_dialog(state: AppState, local: dict, persist, refresh) -> None:
    folder = obsidian_views_folder()
    with ui.dialog() as dialog, ui.card().classes("tv-section").style("min-width:min(520px,92vw)"):
        ui.label("SYNC CONFLICTS").classes("section-header")
        ui.label("These Views changed in both the app and Obsidian since the last sync.").classes("tv-meta")

        def resolve(name: str, side: str):
            view = next((v for v in state.topic_views if v.name == name), None)
            if view is None:
                ui.notify(f"View '{name}' not found in the app.", type="warning")
                return
            result = resolve_conflict(state, view.id, side, folder)
            for warning in result.warnings:
                ui.notify(warning, type="warning", multi_line=True)
            if result.errors:
                ui.notify("; ".join(result.errors), type="negative", multi_line=True)
                return
            local["conflicts"] = [c for c in local["conflicts"] if c != name]
            ui.notify(f"'{name}': kept {'Obsidian' if side == 'vault' else 'app'} version.", type="positive")
            persist()
            dialog.close()
            refresh()

        for name in list(local.get("conflicts", [])):
            with ui.row().style("width:100%;justify-content:space-between;align-items:center;gap:.5rem;margin:.4rem 0"):
                ui.label(name).classes("tv-name")
                with ui.row().style("gap:.35rem"):
                    ui.button("Keep App", on_click=lambda _, n=name: resolve(n, "app")).props("flat dense no-caps")
                    ui.button("Keep Vault", on_click=lambda _, n=name: resolve(n, "vault")).props("flat dense no-caps")
        with ui.row().style("justify-content:flex-end;gap:.5rem;margin-top:.5rem"):
            ui.button("Close", on_click=dialog.close).classes("cancel-btn")
    dialog.open()


def _tag_filter_bar(state: AppState, local: dict, refresh) -> None:
    all_tags = sorted({tag for view in state.topic_views for tag in view.tags if tag != "view"})
    if not all_tags:
        return
    selected = local["tag_filter"]
    with ui.row().style("width:100%;align-items:center;gap:.4rem;flex-wrap:wrap;margin:.75rem 0 .25rem"):
        ui.label("FILTER:").classes("tv-meta").style("font-weight:700")
        for tag in all_tags:
            is_active = tag in selected
            btn = ui.button(tag, color=None, on_click=lambda _, t=tag: _toggle_tag_filter(local, t, refresh)).classes("tv-filter-chip")
            if is_active:
                btn.classes(add="is-active")
        if selected:
            ui.button("Clear", icon="close", on_click=lambda _: (selected.clear(), refresh())).classes("tv-filter-clear").props("flat dense no-caps")


def _toggle_tag_filter(local: dict, tag: str, refresh) -> None:
    selected = local["tag_filter"]
    if tag in selected:
        selected.remove(tag)
    else:
        selected.add(tag)
    refresh()


def _overview(state: AppState, local: dict, persist, refresh) -> None:
    with ui.row().style("width:100%;justify-content:space-between;align-items:flex-start;gap:.75rem;flex-wrap:wrap"):
        with ui.column().style("gap:.15rem"):
            ui.label("MY VIEWS").classes("section-header")
            ui.label("A finite set of arguments you can retrieve and defend.").style("font-size:1.05rem;font-weight:700")
        ui.button("New Topic", icon="add", on_click=lambda: _new_dialog(state, local, persist, refresh)).classes("submit-btn")

    _sync_bar(state, local, persist, refresh)
    _tag_filter_bar(state, local, refresh)

    active = [view for view in state.topic_views if not view.archived]
    # "Needs Attention" is intentionally user-controlled: marking a topic Core
    # is the sole way to place it here. Readiness and practice history remain
    # visible metadata, but do not silently determine this section.
    needs = [view for view in active if view.priority == "Core"]

    selected_tags = local["tag_filter"]
    if selected_tags:
        active = [v for v in active if any(t in selected_tags for t in v.tags)]
        needs = [v for v in needs if any(t in selected_tags for t in v.tags)]

    if not active:
        with ui.element("div").classes("tv-empty").style("margin-top:1rem"):
            if selected_tags:
                ui.label("No Views match the selected tags.").style("font-weight:700")
                ui.button("Clear filters", icon="close", on_click=lambda _: (selected_tags.clear(), refresh())).classes("cancel-btn").style("margin-top:.5rem")
            else:
                ui.label("Build your first View from a blank topic.").style("font-weight:700")
                ui.label("No fabricated content—your thinking stays yours.").classes("tv-meta").style("margin:.35rem 0 .8rem")
                ui.button("New Topic", icon="add", on_click=lambda: _new_dialog(state, local, persist, refresh)).classes("submit-btn")
        return
    if needs:
        ui.label("NEEDS ATTENTION").classes("section-header").style("margin:1.25rem 0 .55rem")
        ui.label("Core Views you have chosen to keep front and center.").classes("tv-meta").style("margin-bottom:.55rem")
        _cards(needs[:6], state, local, persist, refresh)
    ui.label("ALL ACTIVE VIEWS").classes("section-header").style("margin:1.25rem 0 .55rem")
    _cards(active, state, local, persist, refresh)
    archived = [view for view in state.topic_views if view.archived]
    if archived:
        with ui.expansion(f"Archived ({len(archived)})", icon="archive").classes("w-full").style("margin-top:1rem"):
            _cards(archived, state, local, persist, refresh)


def _cards(views, state, local, persist, refresh) -> None:
    with ui.element("div").classes("tv-grid"):
        for view in views:
            with ui.element("div").classes("tv-card") as card:
                with ui.row().style("width:100%;justify-content:space-between;align-items:center;gap:.5rem"):
                    ui.label(view.name).classes("tv-name")
                    ui.label(view.priority).classes("tv-pill")
                ui.label(view.bottom_line or "Bottom line not developed yet.").classes("tv-bottom")
                ui.label(f"{len(view.points)} points · Practiced {_when(view.practice.last_practiced)} · {view.status}").classes("tv-meta")
                visible_tags = [tag for tag in view.tags if tag != "view"]
                if visible_tags:
                    with ui.row().style("gap:.25rem;flex-wrap:wrap;margin-top:.35rem"):
                        for tag in visible_tags:
                            ui.label(tag).classes("tv-card-tag")
                with ui.row().classes("tv-actions").style("gap:.2rem;margin-top:.5rem;justify-content:flex-end"):
                    ui.button("Open", on_click=lambda _, v=view: (local.update(selected=v.id), refresh())).props("flat dense no-caps")
                    ui.button(icon="keyboard_arrow_up", on_click=lambda _, v=view: (_move_topic(state, v, -1), persist(), refresh())).props("flat dense round").tooltip("Move topic up")
                    ui.button(icon="keyboard_arrow_down", on_click=lambda _, v=view: (_move_topic(state, v, 1), persist(), refresh())).props("flat dense round").tooltip("Move topic down")
                    ui.button(icon="unarchive" if view.archived else "archive", on_click=lambda _, v=view: _archive(v, persist, refresh)).props("flat dense round").tooltip("Restore" if view.archived else "Archive")
                    ui.button(icon="delete_outline", on_click=lambda _, v=view: _delete_dialog(v, state, persist, refresh)).props("flat dense round color=negative").tooltip("Delete")
            card.props("draggable=true")
            card.on(
                "click",
                lambda _, v=view: (local.update(selected=v.id), refresh()),
                js_handler="(event) => { if (event.target.closest('button')) return; emit(null); }",
            )
            card.on("dragstart", js_handler=f'(event) => event.dataTransfer.setData("text/plain", "topic:{view.id}")')
            card.on("dragover", js_handler="(event) => event.preventDefault()")
            card.on(
                "drop",
                lambda e, target=view: (_drop_item(state.topic_views, e.args, "topic", target.id), persist(), refresh()),
                js_handler="(event) => { event.preventDefault(); emit(event.dataTransfer.getData('text/plain')); }",
            )


def _new_dialog(state, local, persist, refresh) -> None:
    with ui.dialog() as dialog, ui.card().classes("tv-section").style("min-width:min(430px,92vw)"):
        ui.label("NEW VIEW").classes("section-header")
        name = ui.input(placeholder="Topic name").classes("w-full dark-input")
        def create():
            clean = (name.value or "").strip()
            if not clean:
                ui.notify("Name the topic first.", type="warning"); return
            view = TopicView(name=clean)
            state.topic_views.append(view); persist(); local["selected"] = view.id; dialog.close(); refresh()
        with ui.row().style("justify-content:flex-end;gap:.5rem"):
            ui.button("Cancel", on_click=dialog.close).classes("cancel-btn")
            ui.button("Create", on_click=create).classes("submit-btn")
    dialog.open()


def _archive(view, persist, refresh):
    view.archived = not view.archived; persist(view); refresh()


def _move_topic(state, view, delta):
    peers = [item for item in state.topic_views if item.archived == view.archived]
    index = peers.index(view)
    target = index + delta
    if 0 <= target < len(peers):
        left, right = state.topic_views.index(view), state.topic_views.index(peers[target])
        state.topic_views[left], state.topic_views[right] = state.topic_views[right], state.topic_views[left]


def _delete_dialog(view, state, persist, refresh):
    with ui.dialog() as dialog, ui.card().classes("tv-section"):
        ui.label(f"Delete {view.name}?").style("font-weight:700")
        ui.label("This permanently deletes its structure and practice metadata.").classes("tv-bottom")
        with ui.row().style("justify-content:flex-end;gap:.5rem"):
            ui.button("Cancel", on_click=dialog.close).classes("cancel-btn")
            def delete(): state.topic_views.remove(view); persist(); dialog.close(); refresh()
            ui.button("Delete", on_click=delete).props("color=negative")
    dialog.open()


def _tag_editor(view: TopicView, persist, refresh) -> None:
    """Removable tag chips plus an input to add normalized tags to ``view.tags``."""
    ui.label("TAGS").classes("section-header").style("margin-top:.8rem")
    visible_tags = [tag for tag in view.tags if tag != "view"]
    with ui.row().classes("tv-tag-chips"):
        if not visible_tags:
            ui.label("No tags yet.").classes("tv-meta")
        for tag in visible_tags:
            chip = ui.chip(tag, removable=True, color=None).classes("tv-tag-chip")

            def on_remove(e, t=tag):
                if not e.value and t in view.tags:
                    view.tags.remove(t)
                    persist(view)
                    refresh()

            chip.on_value_change(on_remove)
    with ui.row().style("gap:.4rem;align-items:center;flex-wrap:wrap;margin-top:.4rem"):
        tag_input = ui.input(placeholder="Add tag…").classes("tv-tag-input dark-input").style("min-width:160px")

        def add_tag() -> None:
            raw = (tag_input.value or "").strip().lower()
            if not raw:
                return
            if raw == "view":
                ui.notify("The 'view' tag is managed automatically and cannot be added manually.", type="warning")
                return
            if raw in view.tags:
                ui.notify("Tag already exists.", type="warning")
                return
            view.tags.append(raw)
            persist(view)
            tag_input.value = ""
            refresh()

        tag_input.on("keydown.enter", lambda _: add_tag())
        ui.button("Add", on_click=add_tag).classes("tv-tag-add-btn").props("flat dense no-caps")


def _detail(view, state, local, persist, refresh, practice_view) -> None:
    with ui.row().style("width:100%;justify-content:space-between;align-items:center;gap:.65rem;flex-wrap:wrap"):
        ui.button("All Views", icon="arrow_back", on_click=lambda: (local.update(selected=None, ai=[]), refresh())).classes("cancel-btn")
        with ui.button("Practice This View", icon="record_voice_over").classes("submit-btn"):
            with ui.menu():
                for style in ("Deliver", "Discuss", "Defend"):
                    ui.menu_item(style, on_click=lambda _, s=style: practice_view([view.id], s))
    name = ui.input(value=view.name).classes("w-full dark-input").style("font-size:1.35rem;font-weight:700;margin-top:.8rem")
    name.on("blur", lambda _: _set(view, "name", name.value, persist))
    with ui.row().style("gap:.65rem;align-items:center;flex-wrap:wrap;margin:.45rem 0"):
        status = ui.select(["Developing", "Ready", "Needs Refresh"], value=view.status, label="Status").classes("dark-input").style("min-width:170px")
        status.on_value_change(lambda e: _set(view, "status", e.value, persist))
        priority = ui.select(["Core", "Normal", "Low Priority"], value=view.priority, label="Priority").classes("dark-input").style("min-width:170px")
        priority.on_value_change(lambda e: _set(view, "priority", e.value, persist))
        ui.label(f"Updated {_when(view.updated_at)} · Practiced {_when(view.practice.last_practiced)} · {view.practice.practice_count} sessions").classes("tv-meta")
    _tag_editor(view, persist, refresh)
    ui.label("BOTTOM LINE").classes("section-header").style("margin-top:.8rem")
    bottom = ui.textarea(value=view.bottom_line, placeholder="What is my actual view? Keep it to 1–3 sentences.").classes("w-full dark-input tv-edit")
    bottom.on("blur", lambda _: _set(view, "bottom_line", bottom.value, persist))

    with ui.row().style("gap:.45rem;flex-wrap:wrap;margin:.75rem 0"):
        ui.button("Help Me Structure This", icon="account_tree", on_click=lambda: _structure_dialog(view, persist, refresh)).classes("cancel-btn")
        ui.button("Improve Flow", icon="swap_vert", on_click=lambda: _flow(view, local, persist, refresh)).classes("cancel-btn")
        ui.button("Challenge My View", icon="gavel", on_click=lambda: _challenge(view, local, refresh)).classes("cancel-btn")
    if local["ai"]:
        with ui.element("div").classes("tv-ai"):
            ui.label("AI SUGGESTION").classes("section-header")
            for item in local["ai"]: ui.label(f"• {item}").classes("tv-bottom")
            ui.button("Dismiss", on_click=lambda: (local.update(ai=[]), refresh())).props("flat dense")

    ui.label("MAIN POINTS").classes("section-header").style("margin-top:1rem")
    ui.label("Aim for 2–4. Use the move controls to shape the spoken sequence.").classes("tv-meta")
    for index, point in enumerate(view.points):
        _point(view, point, index, persist, refresh)
    ui.button("Add Main Point", icon="add", on_click=lambda: _add_point(view, persist, refresh)).classes("cancel-btn").style("margin:.45rem 0 1rem")

    _long_field("COUNTERARGUMENT", "What is the strongest argument against this view?", view, "counterargument", persist)
    _long_field("WHAT CHANGES MY MIND?", "What evidence or development would materially change your view?", view, "changes_my_mind", persist)
    if view.practice.latest_diagnostic:
        with ui.element("div").classes("tv-ai"):
            ui.label("RECENT PRACTICE").classes("section-header")
            for item in view.practice.latest_diagnostic: ui.label(f"• {item}").classes("tv-bottom")


def _set(view, field, value, persist):
    setattr(view, field, (value or "").strip() if isinstance(value, str) else value); persist(view)


def _long_field(label, placeholder, view, field, persist):
    ui.label(label).classes("section-header").style("margin-top:1rem")
    control = ui.textarea(value=getattr(view, field), placeholder=placeholder).classes("w-full dark-input tv-edit")
    control.on("blur", lambda _: _set(view, field, control.value, persist))


def _move(items, index, delta):
    target = index + delta
    if 0 <= target < len(items): items[index], items[target] = items[target], items[index]


def _drop_item(items, raw_token, kind, target_id):
    token = raw_token[0] if isinstance(raw_token, list) and raw_token else raw_token
    token = str(token or "")
    prefix = f"{kind}:"
    if not token.startswith(prefix):
        return
    dragged_id = token[len(prefix):]
    source = next((item for item in items if item.id == dragged_id), None)
    target = next((item for item in items if item.id == target_id), None)
    if source is None or target is None or source is target:
        return
    items.remove(source)
    items.insert(items.index(target), source)


def _point(view, point, index, persist, refresh):
    with ui.element("div").classes("tv-point") as point_card:
        with ui.element("div").classes("tv-point-head"):
            handle = ui.label("↕").classes("tv-handle").tooltip("Drag to reorder")
            handle.props("draggable=true")
            handle.on("dragstart", js_handler=f'(event) => event.dataTransfer.setData("text/plain", "point:{point.id}")')
            title = ui.textarea(value=point.title, placeholder=f"Point {index + 1}: concise supporting claim").classes("w-full dark-input").props("autogrow")
            title.on("blur", lambda _, p=point: (_set(p, "title", title.value, lambda __: persist(view))))
            with ui.row().classes("tv-actions").style("gap:.1rem"):
                ui.button(icon="keyboard_arrow_up", on_click=lambda _, i=index: (_move(view.points, i, -1), persist(view), refresh())).props("flat dense round").set_enabled(index > 0)
                ui.button(icon="keyboard_arrow_down", on_click=lambda _, i=index: (_move(view.points, i, 1), persist(view), refresh())).props("flat dense round").set_enabled(index < len(view.points)-1)
                ui.button(icon="delete_outline", on_click=lambda _, p=point: (view.points.remove(p), persist(view), refresh())).props("flat dense round color=negative")
        for fact_index, fact in enumerate(point.facts):
            _fact(view, point, fact, fact_index, persist, refresh)
        ui.button("Add supporting fact", icon="add", on_click=lambda _, p=point: (p.facts.append(ViewFact()), persist(view), refresh())).props("flat dense no-caps").style("margin-left:2rem;color:var(--accent)")
    point_card.on("dragover", js_handler="(event) => event.preventDefault()")
    point_card.on(
        "drop",
        lambda e, target=point: (_drop_item(view.points, e.args, "point", target.id), persist(view), refresh()),
        js_handler="(event) => { event.preventDefault(); emit(event.dataTransfer.getData('text/plain')); }",
    )


def _fact(view, point, fact, index, persist, refresh):
    with ui.element("div").classes("tv-fact") as fact_row:
        handle = ui.label("↕").classes("tv-handle").tooltip("Drag to reorder")
        handle.props("draggable=true")
        handle.on("dragstart", js_handler=f'(event) => event.dataTransfer.setData("text/plain", "fact:{fact.id}")')
        with ui.column().style("gap:.15rem;width:100%"):
            text = ui.textarea(value=fact.text, placeholder="Short supporting fact or subpoint").classes("w-full dark-input").props("autogrow")
            text.on("blur", lambda _, f=fact: (_set(f, "text", text.value, lambda __: persist(view))))
            with ui.expansion("Source / date / note (optional)").classes("w-full"):
                for field, label in (("source", "Source"), ("as_of", "As of"), ("note", "Note")):
                    control = ui.input(value=getattr(fact, field), label=label).classes("w-full dark-input")
                    control.on("blur", lambda _, c=control, f=field: (_set(fact, f, c.value, lambda __: persist(view))))
        with ui.row().classes("tv-actions").style("gap:.05rem"):
            ui.button(icon="keyboard_arrow_up", on_click=lambda _, i=index: (_move(point.facts, i, -1), persist(view), refresh())).props("flat dense round").set_enabled(index > 0)
            ui.button(icon="keyboard_arrow_down", on_click=lambda _, i=index: (_move(point.facts, i, 1), persist(view), refresh())).props("flat dense round").set_enabled(index < len(point.facts)-1)
            ui.button(icon="close", on_click=lambda _, f=fact: (point.facts.remove(f), persist(view), refresh())).props("flat dense round color=negative")
    fact_row.on("dragover", js_handler="(event) => event.preventDefault()")
    fact_row.on(
        "drop",
        lambda e, target=fact: (_drop_item(point.facts, e.args, "fact", target.id), persist(view), refresh()),
        js_handler="(event) => { event.preventDefault(); emit(event.dataTransfer.getData('text/plain')); }",
    )


def _add_point(view, persist, refresh):
    view.points.append(ViewPoint()); persist(view); refresh()


def _structure_dialog(view, persist, refresh):
    with ui.dialog() as dialog, ui.card().classes("tv-section").style("min-width:min(700px,94vw)"):
        ui.label("HELP ME STRUCTURE THIS").classes("section-header")
        notes = ui.textarea(placeholder="Paste messy notes. The result will be a concise proposal, not an essay.").classes("w-full dark-input").style("min-height:220px")
        status = ui.label("").classes("tv-meta")
        async def generate():
            if not llm_available(): status.set_text("Configure OPENROUTER_API_KEY or INTERVIEW_API_KEY first."); return
            if not (notes.value or "").strip(): status.set_text("Paste notes first."); return
            button.disable(); status.set_text("Structuring…")
            try: result = await run.io_bound(lambda: structure_notes(view.name, notes.value or ""))
            except Exception as exc: status.set_text(f"Could not structure notes: {exc}"); button.enable(); return
            dialog.close(); _structure_suggestion(view, result, persist, refresh)
        with ui.row().style("justify-content:flex-end;gap:.5rem"):
            ui.button("Cancel", on_click=dialog.close).classes("cancel-btn")
            button = ui.button("Generate Suggestion", on_click=generate).classes("submit-btn")
    dialog.open()


def _structure_suggestion(view, result, persist, refresh):
    with ui.dialog() as dialog, ui.card().classes("tv-section").style("min-width:min(720px,94vw);max-height:88vh"):
        ui.label("PROPOSED STRUCTURE").classes("section-header")
        ui.label(result.get("bottom_line", "")).classes("tv-bottom")
        for i, point in enumerate(result.get("points", []), 1):
            ui.label(f"{i}. {point.get('title', '')}").style("font-weight:700")
            for fact in point.get("facts", []): ui.label(f"• {fact}").classes("tv-bottom")
        ui.label("Nothing changes until you accept this suggestion.").classes("tv-meta")
        def accept():
            view.bottom_line = str(result.get("bottom_line") or "")
            view.points = [ViewPoint(title=str(p.get("title") or ""), facts=[ViewFact(text=str(f)) for f in p.get("facts", [])]) for p in result.get("points", [])[:4] if isinstance(p, dict)]
            view.counterargument = str(result.get("counterargument") or "")
            view.changes_my_mind = str(result.get("changes_my_mind") or "")
            persist(view); dialog.close(); refresh()
        with ui.row().style("justify-content:flex-end;gap:.5rem"):
            ui.button("Reject", on_click=dialog.close).classes("cancel-btn")
            ui.button("Accept Structure", on_click=accept).classes("submit-btn")
    dialog.open()


async def _flow(view, local, persist, refresh):
    if len(view.points) < 2: ui.notify("Add at least two points first.", type="warning"); return
    if not llm_available(): ui.notify("Configure an interview API key first.", type="warning"); return
    try: result = await run.io_bound(lambda: improve_flow(view))
    except Exception as exc: ui.notify(f"Could not analyze flow: {exc}", type="negative"); return
    ids = result.get("ordered_point_ids", [])
    local["ai"] = [str(result.get("reason") or "A clearer ordering is available.")]
    valid = [point for id_ in ids for point in view.points if point.id == id_]
    if len(valid) != len(view.points): refresh(); return
    with ui.dialog() as dialog, ui.card().classes("tv-section"):
        ui.label("IMPROVE FLOW").classes("section-header")
        ui.label(local["ai"][0]).classes("tv-bottom")
        for i, point in enumerate(valid, 1): ui.label(f"{i}. {point.title}").classes("tv-bottom")
        with ui.row().style("justify-content:flex-end;gap:.5rem"):
            ui.button("Reject", on_click=dialog.close).classes("cancel-btn")
            def accept(): view.points = valid; local["ai"] = []; persist(view); dialog.close(); refresh()
            ui.button("Accept Reorder", on_click=accept).classes("submit-btn")
    dialog.open()


async def _challenge(view, local, refresh):
    if not llm_available(): ui.notify("Configure an interview API key first.", type="warning"); return
    try: result = await run.io_bound(lambda: challenge_view(view))
    except Exception as exc: ui.notify(f"Could not challenge View: {exc}", type="negative"); return
    local["ai"] = [str(item) for item in result.get("observations", [])[:5]]; refresh()
