from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta

from nicegui import ui, run

from storage import research_feeds, user_settings
from storage.research_feeds import PaperSummary, ResearchStore
from services import llm_polish

_MONO = "'IBM Plex Mono','Courier New',monospace"

_SOURCE_COLORS = {
    "FEDS": "#2dd4bf",
    "FEDS Notes": "#8b9cf9",
    "IFDP": "#5eb0f7",
    "NBER": "#fb7185",
    "ECB": "#4ade80",
    "BIS WP": "#facc15",
    "Liberty St": "#c084fc",
    "SF Fed": "#38bdf8",
    "arXiv q-fin": "#f59e6b",
}

_ARXIV_TAG_RE = re.compile(r"^\[(q-fin\.[A-Z]{2})\]\s*")

_RESEARCH_FEED_CSS = """
<style id="mq-research-feed-css">
.rf-controls { display:flex; align-items:center; gap:.5rem; margin-bottom:.85rem; flex-wrap:wrap; width:100%; }
.rf-search { width:min(270px,62vw); font-size:.74rem; }
.rf-chips { display:flex; gap:.4rem; flex-wrap:wrap; align-items:center; }
.rf-toggle { padding:.22rem .65rem; border:1px solid var(--border); border-radius:14px;
             cursor:pointer; font-family:'IBM Plex Mono',monospace; font-size:.62rem;
             color:var(--text-muted); background:transparent; white-space:nowrap; }
.rf-toggle:hover { background:var(--bg-hover); }
.rf-toggle.active { color:var(--accent); border-color:var(--accent); background:var(--accent-glow); }
.rf-counts { font-family:'IBM Plex Mono',monospace; font-size:.62rem; color:var(--text-faint); white-space:nowrap; }
.rf-split { height:calc(100vh - 14rem); min-height:440px; background:var(--bg-primary);
            border:1px solid var(--border); border-radius:8px; overflow:hidden; }
.rf-split .q-splitter__before, .rf-split .q-splitter__after { overflow-y:auto; }
.rf-split .q-splitter__separator { background:var(--border-strong) !important; width:5px; }
.rf-split .q-splitter__separator-icon { color:var(--text-faint); }
.rf-rail { display:flex; flex-direction:column; gap:.3rem; padding:.6rem .65rem; min-width:0; }
.rf-reader { display:flex; flex-direction:column; gap:.55rem; padding:.7rem .9rem 1.2rem; min-width:0; }
.rf-bucket { font-family:'IBM Plex Mono',monospace; font-size:.58rem; font-weight:700;
             letter-spacing:.18em; color:var(--text-faint); margin:.55rem .05rem .05rem; }
.rf-divider { color:#f87171; opacity:.75; margin-top:.75rem; padding-top:.45rem;
              border-top:1px dashed var(--border-strong); }
.rf-item { padding:.45rem .6rem; border:1px solid var(--border); border-radius:6px; cursor:pointer;
           background:var(--bg-primary); transition:background .12s,border-color .12s; }
.rf-item:hover { background:var(--bg-hover); }
.rf-item.selected { border-color:var(--accent); background:var(--accent-glow); }
.rf-item.read { opacity:.55; }
.rf-item-top { display:flex; align-items:center; gap:.4rem; width:100%; }
.rf-item-date { margin-left:auto; font-family:'IBM Plex Mono',monospace; font-size:.56rem;
                color:var(--text-faint); white-space:nowrap; }
.rf-star { color:#fbbf24; font-size:.72rem; line-height:1; }
.rf-mini { font-family:'IBM Plex Mono',monospace; font-size:.52rem; color:var(--text-faint);
           border:1px solid var(--border-strong); border-radius:3px; padding:.05rem .3rem; white-space:nowrap; }
.rf-badge { font-family:'IBM Plex Mono',monospace; font-size:.56rem; font-weight:700;
            letter-spacing:.12em; text-transform:uppercase; padding:.1rem .45rem;
            border-radius:3px; white-space:nowrap; }
.rf-title-lg { font-size:1.02rem; font-weight:700; color:var(--text-primary); line-height:1.4;
               text-decoration:none; }
.rf-title-lg:hover { color:var(--accent); }
.rf-meta { font-family:'IBM Plex Mono',monospace; font-size:.62rem; color:var(--text-faint); }
.rf-actions-row { display:flex; gap:.4rem; flex-wrap:wrap; align-items:center; }
.rf-link-btn { display:inline-flex; align-items:center; gap:.25rem; padding:.24rem .55rem;
               border:1px solid var(--border); border-radius:5px; cursor:pointer;
               color:var(--accent); font-size:.66rem; text-decoration:none;
               font-family:'IBM Plex Mono',monospace; }
.rf-link-btn:hover { background:var(--bg-hover); }
.rf-ai-caption { font-family:'IBM Plex Mono',monospace; font-size:.57rem; color:var(--text-faint);
                 letter-spacing:.03em; margin-top:-0.3rem; }
.rf-section-label { font-family:'IBM Plex Mono',monospace; font-size:.6rem; font-weight:700;
                    letter-spacing:.16em; color:var(--text-muted); margin-top:.15rem; }
.rf-summary { line-height:1.55; font-size:.82rem; color:var(--text-primary);
              background:var(--bg-card); border:1px solid var(--border-strong);
              border-left:3px solid var(--accent); border-radius:6px; padding:.8rem 1rem; }
.rf-summary p { margin:.3rem 0; }
.rf-summary ul, .rf-summary ol { margin:.3rem 0; padding-left:1.15rem; }
.rf-summary li { margin:.18rem 0; }
.rf-summary h1, .rf-summary h2, .rf-summary h3 { font-size:.86rem; margin:.5rem 0 .25rem;
                                                 color:var(--text-primary); }
.rf-summary code { font-family:'IBM Plex Mono','Courier New',monospace; font-size:.78rem;
                   background:var(--bg-hover); border-radius:3px; padding:.05rem .25rem; }
.rf-summary > :first-child { margin-top:0; }
.rf-summary > :last-child { margin-bottom:0; }
.rf-prov { font-family:'IBM Plex Mono',monospace; font-size:.56rem; color:var(--text-faint);
           padding-left:.15rem; line-height:1.5; }
.rf-abs { white-space:pre-wrap; line-height:1.55; font-size:.78rem; color:var(--text-muted);
          background:var(--bg-card); border:1px solid var(--border); border-radius:6px;
          padding:.8rem 1rem; }
.rf-saved { font-family:'IBM Plex Mono',monospace; font-size:.58rem; color:#4ade80; min-height:.9rem; }
.rf-note { font-size:.72rem; color:var(--text-muted); font-family:'IBM Plex Mono',monospace; }
</style>
"""


def _badge(source: str) -> str:
    color = _SOURCE_COLORS.get(source, "#9090b0")
    return (
        f'<span class="rf-badge" style="color:{color}; '
        f'background:{color}1c; border:1px solid {color}44;">{source}</span>'
    )


def _mini_badge(tag: str) -> str:
    return f'<span class="rf-mini">{tag}</span>'


def _split_arxiv_tag(title: str) -> tuple[str, str]:
    m = _ARXIV_TAG_RE.match(title or "")
    if m:
        return m.group(1), title[m.end():]
    return "", title or ""


def _bucket(published: str) -> str:
    if not published:
        return "NEW"
    try:
        d = datetime.strptime(published, "%Y-%m-%d").date()
    except ValueError:
        return "NEW"
    today = date.today()
    if d == today:
        return "TODAY"
    if d == today - timedelta(days=1):
        return "YESTERDAY"
    if d >= today - timedelta(days=7):
        return "THIS WEEK"
    if d >= today - timedelta(days=30):
        return "THIS MONTH"
    return "OLDER"


def render_research_feed() -> None:
    ui.add_head_html(_RESEARCH_FEED_CSS)
    state = {
        "store": research_feeds.load_store(),
        "status": "unread",
        "source": "ALL",
        "search": "",
        "limit": 100,
        "loading": False,
        "selected_id": None,
        "summarizing": False,
        "note_saved": "",
        "demoted": user_settings.deprioritized_sources(),
    }
    prov = llm_polish.paper_provenance()

    header_note = ui.label("").classes("rf-note")

    with ui.row().style("align-items:center; gap:0.75rem; margin-bottom:0.75rem;"):
        ui.label("PAPERS").style(
            f"font-size:0.72rem; font-weight:700; color:var(--accent); "
            f"letter-spacing:0.18em; font-family:{_MONO};"
        )
        ui.button("Refresh feeds", icon="refresh", on_click=lambda: asyncio.ensure_future(_refresh())) \
            .props("flat dense no-caps").style("color:var(--accent)")

    search_input = ui.input(placeholder="Search title / author / abstract…") \
        .props("dense outlined debounce=250").classes("rf-search")
    filter_chips = ui.row().classes("rf-chips")
    counts_lbl = ui.label("").classes("rf-counts")
    ui.space()
    prio_btn = ui.button(icon="tune", on_click=lambda: _open_priority()) \
        .props("flat dense round").style("color:var(--text-muted)")
    prio_btn.tooltip("Source priority - demote noisy sources below the rest")
    ui.button("Mark all read", icon="done_all", on_click=lambda: _all_read()) \
        .props("flat dense no-caps").style("color:var(--text-muted)")

    with ui.splitter(value=32).classes("rf-split w-full") as split:
        with split.before:
            rail = ui.column().classes("rf-rail")
        with split.after:
            reader = ui.column().classes("rf-reader")

    def _safe(fn):
        try:
            fn()
        except RuntimeError as exc:
            if "client this element belongs to has been deleted" not in str(exc):
                raise

    def read_set() -> set:
        return set(state["store"].read_ids)

    def queued_set() -> set:
        return set(state["store"].queued_ids)

    def active_sources() -> list[str]:
        known = [label for label, _ in research_feeds.SOURCES]
        present = {it.source for it in state["store"].items}
        return [s for s in known if s in present] + sorted(present - set(known))

    def matching_items() -> list:
        store: ResearchStore = state["store"]
        read, queued = read_set(), queued_set()
        needle = state["search"].strip().lower()
        out = []
        for it in store.items:
            if state["source"] != "ALL" and it.source != state["source"]:
                continue
            is_read = it.id in read
            is_queued = it.id in queued
            if state["status"] == "unread" and is_read:
                continue
            if state["status"] == "read" and not is_read:
                continue
            if state["status"] == "queue" and not is_queued:
                continue
            if needle and needle not in f"{it.title} {it.authors} {it.summary}".lower():
                continue
            out.append(it)
        return out

    def render_filters():
        filter_chips.clear()
        with filter_chips:
            for label in ("unread", "queue", "read", "all"):
                active = state["status"] == label
                ui.label(label.upper()).classes(f"rf-toggle{' active' if active else ''}") \
                    .on("click", lambda _, l=label: _set_status(l))
            ui.label("·").classes("rf-counts")
            for src in ("ALL", *active_sources()):
                active = state["source"] == src
                ui.label(src.upper()).classes(f"rf-toggle{' active' if active else ''}") \
                    .on("click", lambda _, s=src: _set_source(s))

    def render_rail():
        rail.clear()
        matches = matching_items()
        demoted: set = state["demoted"]
        matches.sort(key=lambda it: (it.source in demoted, bool(it.published)))
        unread_total = research_feeds.unread_count(state["store"])
        counts_lbl.set_text(f"{len(matches)} matched · {unread_total} unread")
        items = matches[: state["limit"]]
        with rail:
            if not matches:
                if not state["store"].items:
                    msg = "Nothing here yet — hit Refresh feeds to pull papers."
                elif state["status"] == "queue":
                    msg = "Queue is empty. Star papers to build a reading queue."
                elif state["status"] == "unread":
                    msg = "No unread papers. Switch to READ or ALL."
                else:
                    msg = "No papers match the current filters."
                ui.label(msg).classes("rf-note").style("padding-top:1.2rem;")
                return
            read, queued = read_set(), queued_set()
            last_bucket = None
            last_tier = False
            for it in items:
                is_demoted = it.source in demoted
                if is_demoted != last_tier:
                    if is_demoted:
                        ui.label("DEMOTED SOURCES").classes("rf-bucket rf-divider")
                    last_tier = is_demoted
                b = _bucket(it.published)
                if b != last_bucket:
                    ui.label(b).classes("rf-bucket")
                    last_bucket = b
                cls = "rf-item"
                if it.id == state["selected_id"]:
                    cls += " selected"
                if it.id in read:
                    cls += " read"
                tag, clean_title = _split_arxiv_tag(it.title)
                with ui.element("div").classes(cls).on("click", lambda _, i=it: _select(i)):
                    with ui.row().classes("rf-item-top").style("flex-wrap:nowrap; align-items:center;"):
                        ui.html(_badge(it.source))
                        if tag:
                            ui.html(_mini_badge(tag))
                        if is_demoted:
                            ui.html('<span class="rf-mini">↓</span>')
                        if it.id in queued:
                            ui.html('<span class="rf-star">★</span>')
                        ui.label(it.published).classes("rf-item-date")
                    ui.label(clean_title).classes("rf-item-title")
                    if it.authors:
                        ui.label(it.authors).classes("rf-item-authors")
            remaining = len(matches) - len(items)
            if remaining > 0:
                ui.button(
                    f"Show more ({remaining} older)",
                    icon="expand_more",
                    on_click=lambda: _more(),
                ).props("flat no-caps").style("color:var(--accent); margin-top:.3rem;")

    def _btn(el, accent: bool = False):
        el.props("flat dense no-caps").style(
            f"color:{'var(--accent)' if accent else 'var(--text-muted)'}; "
            f"font-family:{_MONO}; font-size:.66rem;"
        )
        return el

    def render_reader():
        reader.clear()
        item = next((i for i in state["store"].items if i.id == state["selected_id"]), None)
        with reader:
            if item is None:
                ui.label("Select a paper to read it here.").classes("rf-note").style("padding-top:2rem;")
                return
            is_read = item.id in read_set()
            is_queued = item.id in queued_set()
            summary = state["store"].summaries.get(item.id)
            tag, clean_title = _split_arxiv_tag(item.title)

            with ui.row().style("gap:.5rem; align-items:center; flex-wrap:wrap;"):
                ui.html(_badge(item.source))
                if tag:
                    ui.html(_mini_badge(tag))
                ui.label(item.published).classes("rf-meta")

            ui.link(clean_title, item.url, new_tab=True).classes("rf-title-lg")
            if item.authors:
                ui.label(item.authors).classes("rf-meta")

            with ui.row().classes("rf-actions-row"):
                _btn(ui.button(
                    "mark unread" if is_read else "mark read",
                    icon="undo" if is_read else "check",
                    on_click=lambda _, i=item.id: _toggle_read(i),
                ), accent=not is_read)
                _btn(ui.button(
                    "queued" if is_queued else "queue",
                    icon="bookmark" if is_queued else "bookmark_border",
                    on_click=lambda _, i=item.id: _toggle_queue(i),
                ), accent=is_queued)
                _btn(ui.button(
                    "regenerate ⟳" if summary else "key takeaways ✦",
                    icon="auto_awesome",
                    on_click=lambda _, d=item: asyncio.ensure_future(_summarize(d)),
                ), accent=True)
                ui.html(
                    f'<a class="rf-link-btn" href="{item.url}" target="_blank" rel="noopener">'
                    f'open original ↗</a>'
                )

            ui.label(
                f"ai summaries: {prov['model']} @ {prov['endpoint']} · change under ··· → Settings"
            ).classes("rf-ai-caption")

            if state["summarizing"]:
                with ui.row().style("align-items:center; gap:.5rem;"):
                    ui.spinner("dots", size="1.2rem")
                    ui.label("generating key takeaways…").classes("rf-note")
            elif summary:
                ui.label("KEY TAKEAWAYS").classes("rf-section-label")
                ui.markdown(summary.text, extras=["fenced-code-blocks", "tables", "breaks"]) \
                    .classes("rf-summary")
                ui.label(
                    f"✦ generated by {summary.model or 'unknown model'} "
                    f"via {summary.endpoint or 'unknown endpoint'} · {summary.created_at} "
                    f"· derived from the abstract, not the full paper"
                ).classes("rf-prov")

            ui.label("ABSTRACT").classes("rf-section-label")
            with ui.element("div").classes("rf-abs"):
                ui.label(item.summary or "(no abstract in the feed — open the original)")

            ui.label("MY TAKE").classes("rf-section-label")
            note_input = ui.textarea(
                value=state["store"].notes.get(item.id, ""),
                placeholder="Your read on this paper — implications, disagreements, follow-ups.",
            ).classes("w-full dark-input").props("outlined dense autogrow")
            saved_lbl = ui.label(state["note_saved"]).classes("rf-saved")

            def _commit_note(_e=None):
                research_feeds.save_note(item.id, note_input.value or "")
                state["store"] = research_feeds.load_store()
                state["note_saved"] = f"saved ✓ {datetime.now().strftime('%H:%M')}"
                saved_lbl.set_text(state["note_saved"])

            note_input.on("blur", _commit_note)

    def render_after_change():
        render_filters()
        _safe(render_rail)
        _safe(render_reader)

    def _open_priority():
        demoted_local = set(state["demoted"])
        with ui.dialog() as dialog, ui.card().style(
            "background:var(--bg-card); color:var(--text-primary); "
            f"font-family:{_MONO}; min-width:min(440px,92vw); padding:1.3rem;"
        ):
            ui.label("SOURCE PRIORITY").style(
                f"font-size:.8rem; font-weight:700; color:var(--accent); letter-spacing:.14em;"
            )
            ui.label(
                "Demoted sources sort below everything prioritized, with a divider in the list."
            ).classes("rf-note").style("margin-bottom:.7rem; line-height:1.5;")
            grid = ui.column().style("width:100%; gap:.25rem;")

            def rebuild():
                grid.clear()
                with grid:
                    for label, _url in research_feeds.SOURCES:
                        is_d = label in demoted_local
                        with ui.row().style(
                            "width:100%; align-items:center; justify-content:space-between; gap:.6rem;"
                        ):
                            ui.html(_badge(label))
                            btn = ui.button(
                                "demoted ↓" if is_d else "prioritized",
                                icon="keyboard_double_arrow_down" if is_d else "keyboard_double_arrow_up",
                                on_click=lambda _, l=label: _toggle(l),
                            )
                            btn.props("flat dense no-caps").style(
                                f"color:{'#f87171' if is_d else 'var(--accent)'}; font-family:{_MONO}; font-size:.66rem;"
                            )

            def _toggle(label):
                if label in demoted_local:
                    demoted_local.discard(label)
                else:
                    demoted_local.add(label)
                user_settings.save_deprioritized_sources(sorted(demoted_local))
                rebuild()

            rebuild()
            with ui.row().style("justify-content:flex-end; margin-top:.6rem; width:100%;"):
                ui.button("Done", on_click=dialog.close).classes("submit-btn")
        dialog.open()

        def _on_close():
            state["demoted"] = user_settings.deprioritized_sources()
            render_filters()
            _safe(render_rail)

        dialog.on("hide", lambda _: _on_close())

    def _set_status(label):
        state["status"] = label
        state["limit"] = 100
        render_filters()
        _safe(render_rail)

    def _set_source(src):
        state["source"] = src
        state["limit"] = 100
        render_filters()
        _safe(render_rail)

    def _on_search(e):
        state["search"] = getattr(e, "value", "") or ""
        state["limit"] = 100
        _safe(render_rail)

    def _more():
        state["limit"] += 100
        _safe(render_rail)

    def _show(item):
        state["selected_id"] = item.id
        _safe(render_reader)

    def _select(item):
        if item.id not in read_set():
            research_feeds.mark_read(item.id)
            state["store"] = research_feeds.load_store()
            _safe(render_rail)
        _show(item)

    def _toggle_read(item_id):
        if item_id in read_set():
            research_feeds.mark_unread(item_id)
        else:
            research_feeds.mark_read(item_id)
        state["store"] = research_feeds.load_store()
        render_after_change()

    def _toggle_queue(item_id):
        research_feeds.set_queued(item_id, item_id not in queued_set())
        state["store"] = research_feeds.load_store()
        render_after_change()

    def _all_read():
        research_feeds.mark_all_read()
        state["store"] = research_feeds.load_store()
        header_note.set_text(f"marked {len(state['store'].items)} papers read")
        render_after_change()

    async def _summarize(item):
        if state["summarizing"]:
            return
        if not llm_polish.available():
            ui.notify("Configure an LLM provider and API key in Settings to enable key takeaways.", type="warning")
            return
        parts = [item.title]
        if item.authors:
            parts.append(f"Authors: {item.authors}")
        if item.summary:
            parts.append(item.summary)
        text = "\n\n".join(parts).strip()
        if len(text) < 60:
            ui.notify("Not enough abstract text for this paper.", type="warning")
            return
        state["summarizing"] = True
        _safe(render_reader)
        try:
            result, err = await run.io_bound(llm_polish.summarize_paper, text)
        except Exception as exc:
            result, err = None, str(exc)
        state["summarizing"] = False
        if err or not result:
            ui.notify(f"Key takeaways failed: {err}", type="negative")
            _safe(render_reader)
            return
        p = llm_polish.paper_provenance()
        research_feeds.save_summary(item.id, PaperSummary(
            text=result,
            model=p["model"],
            endpoint=p["endpoint"],
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))
        state["store"] = research_feeds.load_store()
        _safe(render_reader)

    async def _refresh():
        if state["loading"]:
            return
        state["loading"] = True
        header_note.set_text("Fetching feeds…")
        try:
            store, added, note = await run.io_bound(research_feeds.refresh_feeds)
        except Exception as exc:
            header_note.set_text(f"Fetch error: {type(exc).__name__}: {exc}")
            state["loading"] = False
            return
        state["store"] = store
        state["loading"] = False
        header_note.set_text(note)
        render_filters()
        _safe(render_rail)
        if state["selected_id"] is None:
            matches = matching_items()
            if matches:
                _show(matches[0])
                return
        _safe(render_reader)

    search_input.on_value_change(_on_search)

    render_filters()
    render_rail()
    _safe(render_reader)

    if state["selected_id"] is None:
        matches = matching_items()
        if matches:
            _show(matches[0])

    if not state["store"].last_fetch:
        asyncio.ensure_future(_refresh())
    else:
        header_note.set_text(
            f"{len(state['store'].items)} papers cached · fetched {state['store'].last_fetch}"
        )
