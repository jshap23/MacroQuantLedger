"""Fed Watch tab — read FOMC statements, minutes, and speeches with LLM summaries."""
from __future__ import annotations

import asyncio

from nicegui import ui, run

from storage import fed_client
from services import llm_polish

_MONO = "'IBM Plex Mono','Courier New',monospace"

_FED_WATCH_CSS = """
<style id="mq-fed-watch-css">
.fed-split { height:calc(100vh - 13rem); min-height:440px; background:var(--bg-primary);
             border:1px solid var(--border); border-radius:8px; overflow:hidden; }
.fed-split .q-splitter__before, .fed-split .q-splitter__after { overflow-y:auto; }
.fed-split .q-splitter__separator { background:var(--border-strong) !important; width:5px; }
.fed-split .q-splitter__separator-icon { color:var(--text-faint); }
.fed-rail { display:flex; flex-direction:column; gap:.35rem; padding:.6rem .65rem; min-width:0; }
.fed-reader { display:flex; flex-direction:column; gap:.6rem; padding:.7rem .9rem 1.2rem; min-width:0; }
.fed-item { padding:.5rem .7rem; border:1px solid var(--border); border-radius:6px;
            cursor:pointer; background:transparent; transition:background .12s,border-color .12s; }
.fed-item:hover { background:var(--bg-hover); }
.fed-item.selected { border-color:var(--accent); background:var(--accent-glow); }
.fed-item-kind { font-family:'IBM Plex Mono',monospace; font-size:.58rem; font-weight:700;
                 letter-spacing:.14em; color:var(--accent); text-transform:uppercase; }
.fed-item-kind.speech { color:#8b9cf9; }
.fed-item-title { font-size:.82rem; color:var(--text-primary); margin-top:.15rem; line-height:1.35; }
.fed-item-meta { font-family:'IBM Plex Mono',monospace; font-size:.62rem; color:var(--text-faint); margin-top:.2rem; }
.fed-rail-header { font-size:.68rem; font-weight:700; letter-spacing:.18em; color:var(--text-muted);
                   font-family:'IBM Plex Mono',monospace; margin:.75rem .1rem .25rem; }
.fed-doc-text { white-space:pre-wrap; line-height:1.55;
                font-size:.85rem; color:var(--text-primary);
                background:var(--bg-card); border:1px solid var(--border);
                border-radius:6px; padding:1rem 1.15rem; }
.fed-summary { line-height:1.55; font-size:.84rem; color:var(--text-primary);
               background:var(--bg-card); border:1px solid var(--border-strong);
               border-left:3px solid var(--accent);
               border-radius:6px; padding:.85rem 1rem;
               flex:0 0 auto; min-height:0; max-height:220px; overflow-y:auto; }
.fed-summary p { margin:.3rem 0; }
.fed-summary ul, .fed-summary ol { margin:.3rem 0; padding-left:1.15rem; }
.fed-summary li { margin:.18rem 0; }
.fed-summary h1, .fed-summary h2, .fed-summary h3 { font-size:.88rem; margin:.5rem 0 .25rem;
                                                    color:var(--text-primary); }
.fed-summary code { font-family:'IBM Plex Mono','Courier New',monospace; font-size:.8rem;
                    background:var(--bg-hover); border-radius:3px; padding:.05rem .25rem; }
.fed-summary > :first-child { margin-top:0; }
.fed-summary > :last-child { margin-bottom:0; }
.fed-hint { font-size:.72rem; color:var(--text-muted); font-family:'IBM Plex Mono',monospace; }
.fed-link-btn { display:inline-flex; align-items:center; gap:.25rem; padding:.2rem .5rem;
                border:1px solid var(--border); border-radius:5px; cursor:pointer;
                color:var(--accent); font-size:.72rem; text-decoration:none;
                font-family:'IBM Plex Mono',monospace; }
.fed-link-btn:hover { background:var(--bg-hover); }
</style>
"""


def _kind_badge(kind: str) -> str:
    cls = "fed-item-kind speech" if kind == "Speech" else "fed-item-kind"
    return f'<span class="{cls}">{kind}</span>'


def render_fed_watch() -> None:
    ui.add_head_html(_FED_WATCH_CSS)
    state = {
        "fomc": [], "speeches": [],
        "selected_id": None,
        "bodies": {},          # doc_id -> text ('' when fetched but no text version)
        "summaries": {},       # doc_id -> summary
        "requested_bodies": set(),
        "loading": False,
    }

    header_note = ui.label("").classes("fed-hint")

    with ui.row().style("align-items:center; gap:0.75rem; margin-bottom:0.9rem;"):
        ui.label("FED WATCH").style(
            f"font-size:0.72rem; font-weight:700; color:var(--accent); "
            f"letter-spacing:0.18em; font-family:{_MONO};"
        )
        ui.button("Refresh", icon="refresh", on_click=lambda: asyncio.ensure_future(_reload())) \
            .props("flat dense no-caps").style("color:var(--accent)")

    with ui.splitter(value=30).classes("fed-split w-full") as split:
        with split.before:
            rail = ui.column().classes("fed-rail")
        with split.after:
            reader = ui.column().classes("fed-reader")

    def all_docs():
        return state["fomc"] + state["speeches"]

    def _doc_by_id(doc_id):
        return next((d for d in all_docs() if d.id == doc_id), None)

    def _safe(fn):
        try:
            fn()
        except RuntimeError as exc:
            if "client this element belongs to has been deleted" not in str(exc):
                raise

    def render_rail():
        rail.clear()
        with rail:
            if not state["fomc"] and not state["speeches"]:
                ui.label("No communications loaded." + (" Loading…" if state["loading"] else "")).classes("fed-hint")
                return
            ui.label("STATEMENTS & MINUTES").classes("fed-rail-header")
            for doc in state["fomc"]:
                _rail_item(doc)
            ui.label("RECENT SPEECHES").classes("fed-rail-header")
            for doc in state["speeches"]:
                _rail_item(doc)

    def _rail_item(doc):
        selected = doc.id == state["selected_id"]
        with ui.element("div").classes(f"fed-item{' selected' if selected else ''}") \
                .on("click", lambda _, d=doc: _select(d)):
            ui.html(_kind_badge(doc.kind))
            ui.label(doc.title).classes("fed-item-title")
            meta = doc.date or ""
            if doc.kind == "Speech" and doc.speaker:
                meta = f"{doc.speaker} · {meta}" if meta else doc.speaker
            ui.label(meta).classes("fed-item-meta")

    def render_reader():
        reader.clear()
        doc = _doc_by_id(state["selected_id"])
        with reader:
            if doc is None:
                ui.label("Select a document to read.").classes("fed-hint").style("padding-top:2rem;")
                return

            body = state["bodies"].get(doc.id)
            summary = state["summaries"].get(doc.id)

            head_parts = [doc.kind]
            if doc.speaker:
                head_parts.append(doc.speaker)
            if doc.date:
                head_parts.append(doc.date)
            with ui.row().style("align-items:baseline; gap:.6rem; width:100%; flex-wrap:wrap;"):
                ui.label(doc.title).style("font-size:1rem; font-weight:700; color:var(--text-primary);")
                ui.label(" · ".join(head_parts)).classes("fed-hint")
                if doc.venue:
                    ui.label(doc.venue).classes("fed-hint").style("width:100%; margin-top:-0.3rem;")

            with ui.row().style("gap:.6rem; align-items:center;"):
                ui.html(
                    f'<a class="fed-link-btn" href="{doc.url}" target="_blank" rel="noopener">'
                    f'open original ↗</a>'
                )
                if body:
                    cached_summary = llm_polish.get_cached_summary(body) is not None
                    btn_label = "re-summarize ⟳" if summary else "llm summary ✦"
                    btn = ui.button(btn_label, on_click=lambda _, d=doc: asyncio.ensure_future(_summarize(d))) \
                        .props("flat dense no-caps").style(
                            f"color:var(--accent); font-family:{_MONO}; font-size:.72rem;")
                    if cached_summary and not summary:
                        btn.tooltip("Cached summary available — click to regenerate")

            if body is None:
                ui.label("Loading full text…").classes("fed-hint")
            elif body == "":
                ui.label(
                    "No readable text version found for this document — use 'open original'."
                ).classes("fed-hint")
            else:
                if summary:
                    ui.label("AI SUMMARY").style(
                        f"font-size:0.64rem; letter-spacing:0.16em; color:var(--text-muted); "
                        f"font-family:{_MONO};"
                    )
                    ui.markdown(summary, extras=["fenced-code-blocks", "tables", "breaks"]) \
                        .classes("fed-summary")
                with ui.element("div").classes("fed-doc-text"):
                    ui.label(body)

        if body is None and doc.id not in state["requested_bodies"]:
            state["requested_bodies"].add(doc.id)
            asyncio.ensure_future(_load_body(doc))

    async def _load_body(doc):
        try:
            text = await run.io_bound(fed_client.document_body, doc)
        except Exception as exc:
            text = ""
            ui.notify(f"Could not fetch document: {exc}", type="negative")
        state["bodies"][doc.id] = text or ""
        if text and state["selected_id"] == doc.id:
            cached = llm_polish.get_cached_summary(text)
            if cached and doc.id not in state["summaries"]:
                state["summaries"][doc.id] = cached
        _safe(render_reader)

    async def _summarize(doc):
        body = state["bodies"].get(doc.id) or ""
        if not body:
            ui.notify("Document text not loaded yet.", type="warning")
            return
        if not llm_polish.available():
            ui.notify("Configure an LLM provider and API key in Settings to enable summaries.", type="warning")
            return
        try:
            result, err = await run.io_bound(llm_polish.summarize, body)
        except Exception as exc:
            result, err = None, str(exc)
        if err or not result:
            ui.notify(f"Summary failed: {err}", type="negative")
            return
        state["summaries"][doc.id] = result
        _safe(render_reader)

    def _select(doc):
        state["selected_id"] = doc.id
        _safe(render_rail)
        _safe(render_reader)

    async def _reload():
        if state["loading"]:
            return
        state["loading"] = True
        header_note.set_text("Refreshing listings…")
        state["bodies"].clear()
        state["summaries"].clear()
        state["requested_bodies"].clear()

        def _fetch_all():
            fomc, fomc_note = fed_client.fomc_documents()
            speeches, sp_note = fed_client.recent_speeches()
            return fomc, speeches, f"{fomc_note} · {sp_note}"

        try:
            fomc, speeches, note = await run.io_bound(_fetch_all)
        except Exception as exc:
            fomc, speeches, note = [], [], f"Fetch error: {type(exc).__name__}: {exc}"
        state["fomc"] = fomc
        state["speeches"] = speeches
        state["loading"] = False
        header_note.set_text(note)
        _safe(render_rail)
        if state["selected_id"] is None and fomc:
            _select(fomc[0])
        else:
            _safe(render_reader)

    render_rail()
    render_reader()
    asyncio.ensure_future(_reload())
