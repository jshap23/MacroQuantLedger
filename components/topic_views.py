"""Living rolodex for developing, arranging, and practicing structured Views."""
from __future__ import annotations

from datetime import datetime, timezone

from nicegui import run, ui

from models.schema import AppState, TopicView, ViewFact, ViewPoint
from services.topic_views import touch
from storage.persistence import save_state
from storage.topic_view_sync import apply_sync_plan, plan_sync, sync_is_enabled
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
      .tv-dirtybar{position:sticky;top:6px;z-index:60;display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin:.75rem 0;padding:.6rem .85rem;background:var(--bg-card);border:1px solid #f59e0b;border-left:4px solid #f59e0b;border-radius:6px;box-shadow:0 8px 22px rgba(0,0,0,.35)}
      body.light-mode .tv-dirtybar{box-shadow:0 8px 22px rgba(0,0,0,.12)}
      .tv-dirtybar-title{font:700 .72rem 'IBM Plex Mono',monospace;color:#f59e0b;letter-spacing:.09em}
      .tv-dirty-chip{border:1px solid var(--border-strong);border-radius:99px;padding:2px 8px;font:600 .62rem 'IBM Plex Mono',monospace;color:var(--text-muted)}
      .tv-decision{background:var(--bg-card);border:1px solid var(--border-strong);border-radius:7px;padding:.7rem .8rem;margin:.55rem 0}
      .tv-decision-conflict{border-color:#f8717188;border-left:3px solid #f87171}
      .tv-diff{display:grid;grid-template-columns:88px 1fr;gap:.15rem .6rem;margin:.4rem 0;font-size:.76rem}
      .tv-diff-side{font:700 .58rem 'IBM Plex Mono',monospace;color:var(--text-faint);padding-top:.2rem;letter-spacing:.06em}
      .tv-diff-text{color:var(--text-primary);line-height:1.4}
      .tv-toggle-side .q-btn{min-height:28px!important;text-transform:none!important;font:600 .68rem 'IBM Plex Mono',monospace!important}
      .tv-tag-chips{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin:.3rem 0 .15rem}
      .tv-tag-chip{background:var(--accent-glow)!important;border:1px solid var(--border-strong)!important;color:var(--text-primary)!important;font:600 .68rem 'IBM Plex Mono',monospace!important;border-radius:99px!important;min-height:0!important;padding:.25rem .5rem!important}
      .tv-tag-chip .q-chip__content{padding:0!important;font-weight:600!important;font-size:inherit!important}
      .tv-tag-chip .q-chip__icon--remove{color:var(--text-muted)!important;opacity:.65!important;margin-left:.3rem!important;font-size:.85em!important;cursor:pointer!important}
      .tv-tag-chip .q-chip__icon--remove:hover{opacity:1!important;color:var(--accent)!important}
      .tv-tag-input{max-width:220px}
      .tv-tag-add-btn{color:var(--accent)!important}
      .tv-sort-select{min-width:132px}.tv-sort-select .q-field__control{min-height:26px!important;padding:0 .45rem!important;border:1px solid var(--border)!important;border-radius:99px!important;background:var(--bg-input)!important}.tv-sort-select .q-field__native{font:600 .65rem 'IBM Plex Mono',monospace!important;color:var(--text-muted)!important;padding-top:0!important;padding-bottom:0!important;min-height:26px!important}.tv-sort-select .q-field__marginal{height:26px!important;color:var(--text-muted)!important;font-size:.85rem!important}
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


_DRAFT_FIELDS = (
    ("name", "Title"),
    ("status", "Status"),
    ("priority", "Priority"),
    ("tags", "Tags"),
    ("bottom_line", "Bottom line"),
    ("points", "Points"),
    ("counterargument", "Counterargument"),
    ("changes_my_mind", "What changes my mind"),
)


def _draft_for(local: dict, view: TopicView) -> TopicView:
    """Editing copy for the open View; survives re-renders until applied or discarded."""
    if local.get("draft_id") == view.id and isinstance(local.get("draft"), TopicView):
        return local["draft"]
    draft = view.model_copy(deep=True)
    local["draft_id"] = view.id
    local["draft"] = draft
    return draft


def _changed_fields(draft: TopicView, view: TopicView) -> list[str]:
    return [label for field, label in _DRAFT_FIELDS if getattr(draft, field) != getattr(view, field)]


def _is_dirty(local: dict, view: TopicView) -> bool:
    draft = local.get("draft")
    return local.get("draft_id") == view.id and isinstance(draft, TopicView) and bool(_changed_fields(draft, view))


def _drop_draft(local: dict) -> None:
    local["draft_id"] = None
    local["draft"] = None


def render_topic_views(state: AppState, save_indicator, practice_view, open_bridge=None) -> None:
    _inject_css()
    local = {"selected": None, "show_archived": False, "tag_filter": set(), "sort": "manual",
             "draft_id": None, "draft": None}
    root = ui.element("div").classes("tv-shell")

    def persist(view: TopicView | None = None) -> None:
        if view:
            touch(view)
        save_state(state)
        save_indicator()

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

    refresh()


def _pending_decisions(state: AppState) -> list | None:
    try:
        return plan_sync(state).decisions
    except Exception:
        return None


def _sync_bar(state: AppState, local: dict, persist, refresh) -> None:
    folder = obsidian_views_folder()
    enabled = sync_is_enabled()

    with ui.element("div").classes("tv-sync-bar"):
        if not folder:
            ui.label("Obsidian Views folder not configured").classes("tv-sync-label")
        elif not enabled:
            ui.label("Obsidian sync is off").classes("tv-sync-label")
            ui.label(f"folder ready: {folder}").classes("tv-sync-label tv-sync-folder")
        else:
            ui.label("Obsidian folder:").classes("tv-sync-label")
            ui.label(str(folder)).classes("tv-sync-label tv-sync-folder")
            pending = _pending_decisions(state)
            if pending is not None:
                if pending:
                    ui.badge(str(len(pending)), color="warning").tooltip(
                        "Views that differ from your Obsidian vault"
                    )
                    ui.label("pending review").classes("tv-sync-label")
                else:
                    ui.label("in sync").classes("tv-sync-label")
        ui.button("Review & Sync…", icon="sync", on_click=lambda: _sync_review_dialog(state, persist, refresh)).props("flat dense no-caps")


def _sync_review_dialog(state: AppState, persist, refresh) -> None:
    folder = obsidian_views_folder()
    if not folder or not sync_is_enabled():
        ui.notify("Sync is off. Set an Obsidian Views folder and tick 'Enable bidirectional My Views sync' in ··· → Settings.", type="warning", position="top")
        return
    try:
        plan = plan_sync(state)
    except Exception as exc:
        ui.notify(f"Could not compare with Obsidian: {exc}", type="negative")
        return
    for error in plan.errors:
        ui.notify(error, type="warning", multi_line=True)
    if not plan.decisions:
        if not plan.errors:
            ui.notify("Everything matches your Obsidian vault.", type="positive")
        return

    choices: dict[str, str] = {}

    with ui.dialog() as dialog, ui.card().classes("tv-section").style("min-width:min(880px,94vw);max-height:88vh"):
        ui.label("REVIEW SYNC").classes("section-header")
        ui.label("Nothing is written until you apply. Pick a side for each difference; leave both off to skip it.").classes("tv-meta")

        count_lbl = ui.label("0 selected").classes("tv-meta")
        rows = ui.element("div").style("width:100%;max-height:56vh;overflow:auto;padding-right:.2rem")

        async def apply_selected():
            if not choices:
                return
            apply_btn.disable()
            try:
                result = await run.io_bound(lambda: apply_sync_plan(state, plan.decisions, choices))
            except Exception as exc:
                ui.notify(f"Sync failed: {exc}", type="negative")
                apply_btn.enable()
                return
            for warning in result.warnings:
                ui.notify(warning, type="warning", multi_line=True)
            if result.errors:
                ui.notify("; ".join(result.errors), type="negative", multi_line=True)
            parts = []
            if result.exported:
                parts.append(f"{len(result.exported)} exported to Obsidian")
            imported_total = len(result.imported) + len(result.created)
            if imported_total:
                parts.append(f"{imported_total} imported from Obsidian")
            if parts:
                ui.notify("Sync complete: " + ", ".join(parts) + ".", type="positive")
            elif not result.errors:
                ui.notify("Nothing was applied — every selection was skipped.", type="warning")
            if result.imported or result.created:
                persist()
            dialog.close()
            refresh()

        def update_count():
            count_lbl.set_text(f"{len(choices)} selected")
            apply_btn.set_enabled(bool(choices))

        def draw_decision(d) -> None:
            classes = "tv-decision tv-decision-conflict" if d.action == "CONFLICT" else "tv-decision"
            with rows, ui.element("div").classes(classes):
                with ui.row().style("width:100%;justify-content:space-between;align-items:center;gap:.5rem;flex-wrap:wrap"):
                    ui.label(d.name).classes("tv-name")
                    badge_label, badge_color = {
                        "CONFLICT": ("CHANGED IN BOTH", "negative"),
                        "EXPORT": ("CHANGED IN APP", "warning"),
                        "IMPORT": ("CHANGED IN OBSIDIAN", "info"),
                        "CREATE": ("ONLY IN OBSIDIAN", "positive"),
                    }[d.action]
                    ui.badge(badge_label, color=badge_color)
                if d.detail:
                    ui.label(d.detail).classes("tv-diff-text").style("color:#f87171")
                if d.filename:
                    ui.label(d.filename).classes("tv-meta")
                with ui.element("div").classes("tv-diff"):
                    ui.label(f"APP · {d.app_points} pts · {_when(d.app_updated_at)}").classes("tv-diff-side")
                    ui.label(d.app_bottom_line or "—").classes("tv-diff-text")
                    vault_side = f"OBSIDIAN · {d.vault_points} pts · {_when(d.vault_updated_at)}"
                    ui.label(vault_side).classes("tv-diff-side")
                    ui.label(d.vault_bottom_line or "—").classes("tv-diff-text")
                options = {"app": "Use App"}
                if d.action != "CREATE" and d.detail != "Note missing in Obsidian":
                    options["vault"] = "Use Obsidian"

                def on_pick(e, k=d.key):
                    if e.value:
                        choices[k] = e.value
                    else:
                        choices.pop(k, None)
                    update_count()

                ui.toggle(options, value=choices.get(d.key), on_change=on_pick).props("dense no-caps clearable spread").classes("tv-toggle-side")

        with rows:
            ordered = sorted(plan.decisions, key=lambda d: d.action != "CONFLICT")
            for decision in ordered:
                draw_decision(decision)

        with ui.row().style("justify-content:flex-end;gap:.5rem;margin-top:.6rem;width:100%"):
            ui.button("Close", on_click=dialog.close).classes("cancel-btn")
            apply_btn = ui.button("Apply Selected", icon="check_circle", on_click=apply_selected).classes("submit-btn").set_enabled(False)
    dialog.open()


def _unsaved_dialog(local: dict, refresh, proceed) -> None:
    with ui.dialog() as dialog, ui.card().classes("tv-section"):
        ui.label("Unsaved changes").style("font-weight:700")
        ui.label("This View has edits that were not applied yet.").classes("tv-bottom")
        with ui.row().style("justify-content:flex-end;gap:.5rem"):
            ui.button("Keep Editing", on_click=dialog.close).classes("cancel-btn")

            def discard():
                dialog.close()
                _drop_draft(local)
                proceed()

            ui.button("Discard Changes", on_click=discard).props("color=negative")
    dialog.open()


_SORT_OPTIONS = {"manual": "Manual", "name": "Name A–Z", "updated": "Recently Updated", "refresh": "Needs Refresh"}


def _sort_views(views: list[TopicView], mode: str) -> list[TopicView]:
    """Display-only ordering; the stored manual order is never modified."""
    if mode == "name":
        return sorted(views, key=lambda v: v.name.lower())
    if mode == "updated":
        return sorted(views, key=lambda v: v.updated_at.timestamp(), reverse=True)
    if mode == "refresh":
        return sorted(views, key=lambda v: v.status != "Needs Refresh")
    return views


def _tag_filter_bar(state: AppState, local: dict, refresh) -> None:
    all_tags = sorted({tag for view in state.topic_views for tag in view.tags if tag != "view"})
    selected = local["tag_filter"]
    with ui.row().style("width:100%;align-items:center;gap:.4rem;flex-wrap:wrap;margin:.75rem 0 .25rem"):
        if all_tags:
            ui.label("FILTER:").classes("tv-meta").style("font-weight:700")
            for tag in all_tags:
                is_active = tag in selected
                btn = ui.button(tag, color=None, on_click=lambda _, t=tag: _toggle_tag_filter(local, t, refresh)).classes("tv-filter-chip")
                if is_active:
                    btn.classes(add="is-active")
            if selected:
                ui.button("Clear", icon="close", on_click=lambda _: (selected.clear(), refresh())).classes("tv-filter-clear").props("flat dense no-caps")
        ui.element("div").style("flex:1")
        ui.label("SORT:").classes("tv-meta").style("font-weight:700")
        ui.select(_SORT_OPTIONS, value=local["sort"], on_change=lambda e: (local.update(sort=e.value), refresh())).props("dense borderless").classes("tv-sort-select")


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

    sort_mode = local.get("sort", "manual")
    if sort_mode != "manual":
        active = _sort_views(active, sort_mode)

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
        if sort_mode != "manual":
            archived = _sort_views(archived, sort_mode)
        with ui.expansion(f"Archived ({len(archived)})", icon="archive").classes("w-full").style("margin-top:1rem"):
            _cards(archived, state, local, persist, refresh)


def _cards(views, state, local, persist, refresh) -> None:
    manual_order = local.get("sort", "manual") == "manual"
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
                    if manual_order:
                        ui.button(icon="keyboard_arrow_up", on_click=lambda _, v=view: (_move_topic(state, v, -1), persist(), refresh())).props("flat dense round").tooltip("Move topic up")
                        ui.button(icon="keyboard_arrow_down", on_click=lambda _, v=view: (_move_topic(state, v, 1), persist(), refresh())).props("flat dense round").tooltip("Move topic down")
                    if view.archived:
                        ui.button("Restore", icon="unarchive", on_click=lambda _, v=view: _restore(v, persist, refresh)).props("flat dense no-caps")
                    ui.button(icon="delete_outline", on_click=lambda _, v=view: _delete_dialog(v, state, persist, refresh)).props("flat dense round color=negative").tooltip("Delete")
            card.on(
                "click",
                lambda _, v=view: (local.update(selected=v.id), refresh()),
                js_handler="(event) => { if (event.target.closest('button')) return; emit(null); }",
            )
            if manual_order:
                card.props("draggable=true")
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


def _restore(view, persist, refresh):
    view.archived = False
    persist(view)
    ui.notify(f"'{view.name}' restored to active Views.", type="positive")
    refresh()


def _archive_dialog(view, local, persist, refresh):
    with ui.dialog() as dialog, ui.card().classes("tv-section"):
        ui.label(f"Archive '{view.name}'?").style("font-weight:700")
        ui.label(
            "It moves to the Archived list at the bottom of My Views. The note stays in your "
            "Obsidian vault (archived: true) and practice history is kept. You can restore it anytime."
        ).classes("tv-bottom")
        with ui.row().style("justify-content:flex-end;gap:.5rem"):
            ui.button("Cancel", on_click=dialog.close).classes("cancel-btn")

            def archive():
                dialog.close()
                view.archived = True
                persist(view)
                _drop_draft(local)
                local["selected"] = None
                ui.notify(f"'{view.name}' archived.", type="positive")
                refresh()

            ui.button("Archive", on_click=archive).props("color=negative")
    dialog.open()


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


def _tag_editor(obj: TopicView, refresh) -> None:
    """Removable tag chips plus an input to add normalized tags to the draft."""
    ui.label("TAGS").classes("section-header").style("margin-top:.8rem")
    visible_tags = [tag for tag in obj.tags if tag != "view"]
    with ui.row().classes("tv-tag-chips"):
        if not visible_tags:
            ui.label("No tags yet.").classes("tv-meta")
        for tag in visible_tags:
            chip = ui.chip(tag, removable=True, color=None).classes("tv-tag-chip")

            def on_remove(e, t=tag):
                if not e.value and t in obj.tags:
                    obj.tags.remove(t)
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
            if raw in obj.tags:
                ui.notify("Tag already exists.", type="warning")
                return
            obj.tags.append(raw)
            tag_input.value = ""
            refresh()

        tag_input.on("keydown.enter", lambda _: add_tag())
        ui.button("Add", on_click=add_tag).classes("tv-tag-add-btn").props("flat dense no-caps")


def _detail(view, state, local, persist, refresh, practice_view) -> None:
    draft = _draft_for(local, view)

    def guarded(action):
        def go():
            if _is_dirty(local, view):
                _unsaved_dialog(local, refresh, action)
            else:
                action()
        return go

    with ui.row().style("width:100%;justify-content:space-between;align-items:center;gap:.65rem;flex-wrap:wrap"):
        ui.button("All Views", icon="arrow_back", on_click=guarded(lambda: (local.update(selected=None), refresh()))).classes("cancel-btn")
        with ui.button("Practice This View", icon="record_voice_over").classes("submit-btn"):
            with ui.menu():
                for style in ("Deliver", "Discuss", "Defend"):
                    ui.menu_item(style, on_click=guarded(lambda style=style: practice_view([view.id], style)))

    bar_slot = ui.element("div")

    def apply_changes():
        view.name = draft.name.strip() or view.name
        view.status = draft.status
        view.priority = draft.priority
        view.tags = list(draft.tags)
        view.bottom_line = draft.bottom_line.strip()
        view.counterargument = draft.counterargument.strip()
        view.changes_my_mind = draft.changes_my_mind.strip()
        view.points = draft.points
        touch(view)
        persist()
        _drop_draft(local)
        ui.notify("View updated.", type="positive")
        refresh()

    def draw_bar():
        bar_slot.clear()
        changes = _changed_fields(draft, view)
        if not changes:
            return
        with bar_slot:
            with ui.element("div").classes("tv-dirtybar"):
                ui.icon("edit_note", color="warning")
                ui.label("UNSAVED CHANGES").classes("tv-dirtybar-title")
                for label in changes:
                    ui.label(label).classes("tv-dirty-chip")
                ui.element("div").style("flex:1")
                ui.button("Discard", icon="undo", on_click=lambda: (_drop_draft(local), refresh())).props("flat dense no-caps")
                ui.button("Apply Changes", icon="check_circle", on_click=apply_changes).props("unelevated no-caps")

    def set_field(obj, field, value):
        setattr(obj, field, (value or "").strip() if isinstance(value, str) else value)
        draw_bar()

    draw_bar()

    name = ui.input(value=draft.name).classes("w-full dark-input").style("font-size:1.35rem;font-weight:700;margin-top:.8rem")
    name.on("blur", lambda _: set_field(draft, "name", name.value))
    with ui.row().style("gap:.65rem;align-items:center;flex-wrap:wrap;margin:.45rem 0"):
        status = ui.select(["Developing", "Ready", "Needs Refresh"], value=draft.status, label="Status").classes("dark-input").style("min-width:170px")
        status.on_value_change(lambda e: set_field(draft, "status", e.value))
        priority = ui.select(["Core", "Normal", "Low Priority"], value=draft.priority, label="Priority").classes("dark-input").style("min-width:170px")
        priority.on_value_change(lambda e: set_field(draft, "priority", e.value))
        ui.label(f"Updated {_when(view.updated_at)} · Practiced {_when(view.practice.last_practiced)} · {view.practice.practice_count} sessions").classes("tv-meta")
    _tag_editor(draft, refresh)
    ui.label("BOTTOM LINE").classes("section-header").style("margin-top:.8rem")
    bottom = ui.textarea(value=draft.bottom_line, placeholder="What is my actual view? Keep it to 1–3 sentences.").classes("w-full dark-input tv-edit")
    bottom.on("blur", lambda _: set_field(draft, "bottom_line", bottom.value))

    ui.label("MAIN POINTS").classes("section-header").style("margin-top:1rem")
    ui.label("Aim for 2–4. Use the move controls to shape the spoken sequence.").classes("tv-meta")
    for index, point in enumerate(draft.points):
        _point(draft, point, index, draw_bar, refresh)
    ui.button("Add Main Point", icon="add", on_click=lambda: _add_point(draft, refresh)).classes("cancel-btn").style("margin:.45rem 0 1rem")

    _long_field("COUNTERARGUMENT", "What is the strongest argument against this view?", draft, "counterargument", set_field)
    _long_field("WHAT CHANGES MY MIND?", "What evidence or development would materially change your view?", draft, "changes_my_mind", set_field)
    if view.practice.latest_diagnostic:
        with ui.element("div").classes("tv-ai"):
            ui.label("RECENT PRACTICE").classes("section-header")
            for item in view.practice.latest_diagnostic: ui.label(f"• {item}").classes("tv-bottom")

    def ask_archive():
        if _is_dirty(local, view):
            ui.notify("Apply or discard your edits before archiving.", type="warning")
            return
        _archive_dialog(view, local, persist, refresh)

    with ui.row().style("margin-top:2.25rem;padding-top:.8rem;border-top:1px solid var(--border);width:100%;justify-content:flex-end"):
        ui.button("Archive This View…", icon="archive", on_click=ask_archive).props("flat dense no-caps color=negative")


def _set(obj, field, value, after=None):
    setattr(obj, field, (value or "").strip() if isinstance(value, str) else value)
    if after:
        after()


def _long_field(label, placeholder, obj, field, set_field):
    ui.label(label).classes("section-header").style("margin-top:1rem")
    control = ui.textarea(value=getattr(obj, field), placeholder=placeholder).classes("w-full dark-input tv-edit")
    control.on("blur", lambda _: set_field(obj, field, control.value))


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


def _point(holder, point, index, bump, refresh):
    with ui.element("div").classes("tv-point") as point_card:
        with ui.element("div").classes("tv-point-head"):
            handle = ui.label("↕").classes("tv-handle").tooltip("Drag to reorder")
            handle.props("draggable=true")
            handle.on("dragstart", js_handler=f'(event) => event.dataTransfer.setData("text/plain", "point:{point.id}")')
            title = ui.textarea(value=point.title, placeholder=f"Point {index + 1}: concise supporting claim").classes("w-full dark-input").props("autogrow")
            title.on("blur", lambda _, p=point: _set(p, "title", title.value, bump))
            with ui.row().classes("tv-actions").style("gap:.1rem"):
                ui.button(icon="keyboard_arrow_up", on_click=lambda _, i=index: (_move(holder.points, i, -1), refresh())).props("flat dense round").set_enabled(index > 0)
                ui.button(icon="keyboard_arrow_down", on_click=lambda _, i=index: (_move(holder.points, i, 1), refresh())).props("flat dense round").set_enabled(index < len(holder.points)-1)
                ui.button(icon="delete_outline", on_click=lambda _, p=point: (holder.points.remove(p), refresh())).props("flat dense round color=negative")
        for fact_index, fact in enumerate(point.facts):
            _fact(point, fact, fact_index, bump, refresh)
        ui.button("Add supporting fact", icon="add", on_click=lambda _, p=point: (p.facts.append(ViewFact()), refresh())).props("flat dense no-caps").style("margin-left:2rem;color:var(--accent)")
    point_card.on("dragover", js_handler="(event) => event.preventDefault()")
    point_card.on(
        "drop",
        lambda e, target=point: (_drop_item(holder.points, e.args, "point", target.id), refresh()),
        js_handler="(event) => { event.preventDefault(); emit(event.dataTransfer.getData('text/plain')); }",
    )


def _fact(point, fact, index, bump, refresh):
    with ui.element("div").classes("tv-fact") as fact_row:
        handle = ui.label("↕").classes("tv-handle").tooltip("Drag to reorder")
        handle.props("draggable=true")
        handle.on("dragstart", js_handler=f'(event) => event.dataTransfer.setData("text/plain", "fact:{fact.id}")')
        with ui.column().style("gap:.15rem;width:100%"):
            text = ui.textarea(value=fact.text, placeholder="Short supporting fact or subpoint").classes("w-full dark-input").props("autogrow")
            text.on("blur", lambda _, f=fact: _set(f, "text", text.value, bump))
            with ui.expansion("Source / date / note (optional)").classes("w-full"):
                for field, label in (("source", "Source"), ("as_of", "As of"), ("note", "Note")):
                    control = ui.input(value=getattr(fact, field), label=label).classes("w-full dark-input")
                    control.on("blur", lambda _, c=control, f=field: _set(fact, f, c.value, bump))
        with ui.row().classes("tv-actions").style("gap:.05rem"):
            ui.button(icon="keyboard_arrow_up", on_click=lambda _, i=index: (_move(point.facts, i, -1), refresh())).props("flat dense round").set_enabled(index > 0)
            ui.button(icon="keyboard_arrow_down", on_click=lambda _, i=index: (_move(point.facts, i, 1), refresh())).props("flat dense round").set_enabled(index < len(point.facts)-1)
            ui.button(icon="close", on_click=lambda _, f=fact: (point.facts.remove(f), refresh())).props("flat dense round color=negative")
    fact_row.on("dragover", js_handler="(event) => event.preventDefault()")
    fact_row.on(
        "drop",
        lambda e, target=fact: (_drop_item(point.facts, e.args, "fact", target.id), refresh()),
        js_handler="(event) => { event.preventDefault(); emit(event.dataTransfer.getData('text/plain')); }",
    )


def _add_point(holder, refresh):
    holder.points.append(ViewPoint())
    refresh()
