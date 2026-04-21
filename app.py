from __future__ import annotations
import asyncio
from nicegui import ui, app as ni_app
from storage.persistence import load_state, save_state, import_state, STATE_FILE
from components.status_bar import render_status_bar
from components.macro_views import render_macro_views
from components.quant_tracker import render_quant_tracker
from components.reconciliation import render_reconciliation
from components.asset_views import render_asset_views
from components.briefing_strip import render_briefing_strip
from components.view_change_log import render_view_change_log
from components.fred_panel import render_fred_panel
from models.schema import ViewChangeEntry
from export.excel import generate_excel
from export.obsidian import generate_obsidian_note

# ── CSS ────────────────────────────────────────────────────────────────────────
CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap');

/* ── CSS Variables: dark mode (default) ── */
:root {
    --bg-primary:    #0f0f13;
    --bg-card:       #17171e;
    --bg-input:      #0f0f13;
    --bg-hover:      #1e1e28;
    --bg-status:     #13131a;
    --border:        #23232e;
    --border-strong: #2e2e3e;
    --text-primary:  #dddde8;
    --text-muted:    #9090b0;
    --text-faint:    #60607a;
    --accent:        #2dd4bf;
    --accent-dim:    #0d2e2b;
    --accent-glow:   #2dd4bf18;
    --tab-bg:        #13131a;
}

/* ── CSS Variables: light mode ── */
body.light-mode {
    --bg-primary:    #f4f4f8;
    --bg-card:       #ffffff;
    --bg-input:      #f9f9fc;
    --bg-hover:      #eeeef4;
    --bg-status:     #eaeaf0;
    --border:        #d8d8e4;
    --border-strong: #c4c4d4;
    --text-primary:  #18181e;
    --text-muted:    #6b6b82;
    --text-faint:    #b0b0c0;
    --accent:        #0f766e;
    --accent-dim:    #ccfbf1;
    --accent-glow:   #0f766e18;
    --tab-bg:        #eaeaf0;
}

/* ── Base ── */
*, *::before, *::after { box-sizing: border-box; }

body, .q-page, .nicegui-content {
    background: var(--bg-primary) !important;
    color: var(--text-primary) !important;
    font-family: 'IBM Plex Mono', 'Courier New', monospace !important;
    transition: background 0.2s, color 0.2s;
}

/* ── Header ── */
.app-header {
    background: var(--bg-primary);
    border-bottom: 1px solid var(--border);
    padding: 0.85rem 1.5rem 0.85rem 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
}
.app-title-block { flex-shrink: 0; min-width: 0; }
.app-title {
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--accent) !important;
    letter-spacing: 0.12em;
    font-family: 'IBM Plex Mono', monospace !important;
    white-space: nowrap;
}
.app-subtitle {
    font-size: 0.68rem;
    color: var(--text-muted) !important;
    letter-spacing: 0.08em;
    margin-top: 2px;
    font-family: 'IBM Plex Mono', monospace !important;
    white-space: nowrap;
}
.header-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-shrink: 0;
}

/* ── Status bar ── */
.status-bar {
    background: var(--bg-status);
    border-bottom: 1px solid var(--border);
    padding: 0.55rem 2rem;
    gap: 2.5rem;
    align-items: center;
}
.status-indicator { display: flex; flex-direction: column; gap: 1px; }
.status-label {
    font-size: 0.62rem;
    color: var(--text-muted);
    letter-spacing: 0.12em;
    font-weight: 700;
    font-family: 'IBM Plex Mono', monospace !important;
}

/* ── Saved toast ── */
.saved-toast {
    position: fixed;
    top: 1rem;
    right: 1.5rem;
    background: #0f2a1a;
    color: #4ade80;
    padding: 4px 14px;
    border-radius: 4px;
    font-size: 0.72rem;
    border: 1px solid #4ade8044;
    z-index: 9999;
    font-family: 'IBM Plex Mono', monospace !important;
}
body.light-mode .saved-toast {
    background: #dcfce7;
    color: #166534;
    border-color: #86efac;
}

/* ── Tabs ── */
.q-tabs {
    background: var(--tab-bg) !important;
    border-bottom: 1px solid var(--border) !important;
}
.q-tab {
    color: var(--text-muted) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
}
.q-tab--active { color: var(--accent) !important; }
.q-tab-indicator { background: var(--accent) !important; }
.q-tab-panels { background: var(--bg-primary) !important; }
.q-tab-panel {
    padding: 1.5rem 2rem !important;
    background: var(--bg-primary) !important;
}

/* ── Section / field labels ── */
.section-header {
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    color: var(--accent) !important;
    letter-spacing: 0.18em;
    margin-bottom: 0.75rem;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.3rem;
    font-family: 'IBM Plex Mono', monospace !important;
    width: 100%;
}
.field-label {
    font-size: 0.62rem !important;
    color: var(--text-muted) !important;
    letter-spacing: 0.12em;
    font-weight: 700 !important;
    margin-top: 0.6rem;
    margin-bottom: 2px;
    font-family: 'IBM Plex Mono', monospace !important;
}

/* ── Inputs ── */
.dark-input .q-field__control {
    background: var(--bg-input) !important;
    border: 1px solid var(--border) !important;
    border-radius: 4px !important;
    color: var(--text-primary) !important;
    transition: border-color 0.15s;
}
.dark-input .q-field__control:hover,
.dark-input .q-field__control:focus-within {
    border-color: var(--accent) !important;
}
.dark-input .q-field__native,
.dark-input .q-field__input,
.dark-input textarea {
    color: var(--text-primary) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.84rem !important;
}
.dark-input .q-field__label { color: var(--text-muted) !important; }
.dark-input .q-field__bottom { display: none !important; }



/* ── Asset view rows ── */
.asset-row-l1 {
    background: var(--bg-card);
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.6rem 0.9rem;
    margin-bottom: 0.75rem;
}
.asset-row-l2 {
    padding: 0.35rem 0.6rem;
    border-radius: 4px;
    border-bottom: 1px solid var(--border);
    transition: background 0.1s;
}
.asset-row-l2:hover { background: var(--bg-hover); }
.asset-row-l2:last-child { border-bottom: none; }

/* ── Reconciliation ── */
.recon-form-card {
    background: var(--bg-card);
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 1.25rem;
    margin-bottom: 1.5rem;
    width: 100%;
}
.recon-history-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.45rem;
    transition: border-color 0.15s;
}

/* ── Buttons ── */
.add-btn {
    background: transparent !important;
    border: 1px dashed var(--border-strong) !important;
    color: var(--text-muted) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.75rem !important;
    width: 100% !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    transition: border-color 0.15s, color 0.15s !important;
}
.add-btn:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
    background: var(--accent-glow) !important;
}
.remove-btn {
    background: transparent !important;
    color: var(--text-faint) !important;
    font-size: 0.8rem !important;
    padding: 2px 7px !important;
    min-height: unset !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    transition: color 0.12s, background 0.12s !important;
}
.remove-btn:hover {
    color: #f87171 !important;
    background: #3a111122 !important;
}
.submit-btn {
    background: var(--accent) !important;
    color: #fff !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-weight: 700 !important;
    border-radius: 4px !important;
    box-shadow: none !important;
}
.submit-btn:hover { opacity: 0.88 !important; }
.cancel-btn {
    background: transparent !important;
    color: var(--text-muted) !important;
    border: 1px solid var(--border) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    border-radius: 4px !important;
    box-shadow: none !important;
}
.export-btn {
    background: var(--accent) !important;
    color: #fff !important;
    font-weight: 700 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    border-radius: 4px !important;
    padding: 0 1rem !important;
    box-shadow: none !important;
    white-space: nowrap !important;
}
.export-btn:hover { opacity: 0.88 !important; }
.import-btn {
    background: transparent !important;
    color: var(--accent) !important;
    border: 1px solid var(--accent) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    white-space: nowrap !important;
    padding: 0 1rem !important;
}
.import-btn:hover {
    background: var(--accent-glow) !important;
    opacity: 1 !important;
}
.reset-btn {
    background: transparent !important;
    color: var(--text-muted) !important;
    border: 1px solid var(--border) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    white-space: nowrap !important;
    font-size: 0.78rem !important;
}
.reset-btn:hover {
    color: #f87171 !important;
    border-color: #f8717144 !important;
}
.theme-btn {
    background: transparent !important;
    color: var(--text-muted) !important;
    border: 1px solid var(--border) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    min-width: 2.2rem !important;
    padding: 0 0.5rem !important;
}
.theme-btn:hover {
    color: var(--accent) !important;
    border-color: var(--accent) !important;
}

/* ── Dialog ── */
.q-dialog__backdrop { background: rgba(0,0,0,0.7) !important; }

/* ── Misc ── */
.w-full { width: 100% !important; }
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }

/* Light mode Quasar overrides */
body.light-mode .q-card,
body.light-mode .q-dialog .q-card { background: #fff !important; color: #18181e !important; }
body.light-mode .q-select__dropdown-icon { color: var(--text-muted) !important; }

/* ── Mobile responsive ── */
@media (max-width: 640px) {
    .app-header {
        padding: 0.6rem 0.9rem;
        flex-wrap: wrap;
        gap: 0.6rem;
    }
    .app-subtitle { display: none; }
    .header-actions { gap: 0.3rem; flex-wrap: wrap; }
    .status-bar {
        padding: 0.5rem 0.9rem;
        gap: 1rem;
        flex-wrap: wrap;
    }
    .q-tab-panel { padding: 0.75rem 0.75rem !important; }
    .q-tab {
        font-size: 0.68rem !important;
        letter-spacing: 0.04em !important;
        padding: 0 0.5rem !important;
    }

}
"""


# ── App ────────────────────────────────────────────────────────────────────────

state = None


def get_state():
    global state
    if state is None:
        state = load_state()
    return state


@ni_app.on_startup
def startup():
    get_state()


def show_saved(label_el):
    async def _show():
        label_el.set_visibility(True)
        await asyncio.sleep(1.5)
        label_el.set_visibility(False)
    asyncio.ensure_future(_show())


@ui.page("/")
def index():
    dark = ui.dark_mode()
    dark.enable()
    ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    ui.add_css(CUSTOM_CSS)

    s = get_state()

    # Saved toast
    saved_el = ui.element("div").classes("saved-toast")
    saved_el.set_visibility(False)
    with saved_el:
        ui.label("✓ saved")

    status_container = {"el": None}

    def refresh_status():
        if status_container["el"] is not None:
            status_container["el"].clear()
            with status_container["el"]:
                render_status_bar(s)

    def save_indicator():
        show_saved(saved_el)
        refresh_status()

    # ── Header ────────────────────────────────────────────────────────────────
    with ui.element("div").classes("app-header"):
        with ui.element("div").classes("app-title-block"):
            ui.label("MACROQUANT LEDGER").classes("app-title")
            ui.label("view inventory · quant tracker · reconciliation").classes("app-subtitle")

        with ui.element("div").classes("header-actions"):
            # Dark/light toggle
            is_dark = {"v": True}

            def toggle_theme():
                is_dark["v"] = not is_dark["v"]
                if is_dark["v"]:
                    dark.enable()
                    ui.run_javascript("document.body.classList.remove('light-mode')")
                    theme_btn.set_text("☀")
                    theme_btn.tooltip("Switch to light mode")
                else:
                    dark.disable()
                    ui.run_javascript("document.body.classList.add('light-mode')")
                    theme_btn.set_text("🌙")
                    theme_btn.tooltip("Switch to dark mode")

            theme_btn = ui.button("☀", on_click=toggle_theme).classes("theme-btn")
            theme_btn.tooltip("Switch to light mode")

            def do_export():
                path = generate_excel(s)
                ui.download(str(path))

            ui.button("Export Excel", on_click=do_export).classes("export-btn")

            def do_export_obsidian():
                try:
                    path = generate_obsidian_note(s)
                    ui.notify(
                        f"Obsidian note written: {path}",
                        type="positive",
                        position="top",
                    )
                except OSError as exc:
                    ui.notify(f"Could not write Obsidian note: {exc}", type="negative", position="top")

            ui.button(
                "Obsidian",
                icon="edit_note",
                on_click=do_export_obsidian,
            ).classes("export-btn").tooltip("Export markdown to JS_Obsidian/MacroQuant")

            def do_export_json():
                ui.download(str(STATE_FILE), "macroquant_state.json")

            ui.button("Export JSON", on_click=do_export_json).classes("import-btn")

            def do_import():
                with ui.dialog() as dialog, ui.card().style(
                    "background:var(--bg-card); color:var(--text-primary); "
                    "font-family:'IBM Plex Mono',monospace; min-width:min(380px,90vw); padding:1.5rem;"
                ):
                    ui.label("Import State").style(
                        "font-size:1rem; font-weight:700; color:var(--accent); margin-bottom:0.5rem;"
                    )
                    ui.label(
                        "Upload a previously exported macroquant_state.json file. "
                        "Your current data will be replaced immediately."
                    ).style(
                        "color:var(--text-muted); font-size:0.8rem; margin-bottom:1.25rem; line-height:1.6;"
                    )

                    status_label = ui.label("").style(
                        "font-size:0.78rem; color:#f87171; min-height:1.2em;"
                    )

                    def handle_upload(e):
                        global state
                        try:
                            content = e.content.read().decode("utf-8")
                            state = import_state(content)
                            dialog.close()
                            ui.navigate.reload()
                        except ValueError as exc:
                            status_label.set_text(str(exc))
                        except Exception as exc:
                            status_label.set_text(f"Unexpected error: {exc}")

                    ui.upload(
                        label="Choose state.json",
                        auto_upload=True,
                        on_upload=handle_upload,
                    ).props("accept=.json").style(
                        "font-family:'IBM Plex Mono',monospace; font-size:0.8rem;"
                    )

                    with ui.row().style("gap:0.5rem; justify-content:flex-end; margin-top:1rem;"):
                        ui.button("Cancel", on_click=dialog.close).style(
                            "background:transparent; color:var(--text-muted); "
                            "border:1px solid var(--border); box-shadow:none; "
                            "font-family:'IBM Plex Mono',monospace;"
                        )

                dialog.open()

            ui.button("Import JSON", on_click=do_import).classes("import-btn")

            def do_reset():
                with ui.dialog() as dialog, ui.card().style(
                    "background:var(--bg-card); color:var(--text-primary); "
                    "font-family:'IBM Plex Mono',monospace; min-width:min(340px,90vw); padding:1.5rem;"
                ):
                    ui.label("Reset All Data").style(
                        "font-size:1rem; font-weight:700; color:var(--accent); margin-bottom:0.5rem;"
                    )
                    ui.label(
                        "This will erase all macro views, quant tracker entries, and reconciliation history and restore defaults. This cannot be undone."
                    ).style("color:var(--text-muted); font-size:0.8rem; margin-bottom:1.25rem; line-height:1.6;")
                    with ui.row().style("gap:0.5rem; justify-content:flex-end;"):
                        ui.button("Cancel", on_click=dialog.close).style(
                            "background:transparent; color:var(--text-muted); "
                            "border:1px solid var(--border); box-shadow:none; "
                            "font-family:'IBM Plex Mono',monospace;"
                        )

                        def confirm_reset():
                            global state
                            from models.schema import default_state
                            state = default_state()
                            save_state(state)
                            dialog.close()
                            ui.navigate.reload()

                        ui.button("Yes, reset everything", on_click=confirm_reset).style(
                            "background:#7f1d1d; color:#fca5a5; border:1px solid #991b1b; "
                            "box-shadow:none; font-family:'IBM Plex Mono',monospace; font-weight:700;"
                        )
                dialog.open()

            ui.button("Reset Data", on_click=do_reset).classes("reset-btn")

    # ── Status Bar ────────────────────────────────────────────────────────────
    status_container["el"] = ui.element("div").style("width:100%;")
    with status_container["el"]:
        render_status_bar(s)

    # ── View change logger ─────────────────────────────────────────────────────
    def log_change(view, field: str, old_val: str, new_val: str):
        if old_val == new_val:
            return
        from datetime import datetime, timezone
        entry = ViewChangeEntry(
            timestamp=datetime.now(tz=timezone.utc),
            view_id=view.id,
            view_name=view.name,
            field=field,
            old_value=old_val,
            new_value=new_val,
        )
        s.view_change_log.insert(0, entry)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    # ── FRED data: load in background, update panel when ready ────────────────
    fred_ref = {"container": None}

    async def _load_fred():
        from nicegui import run
        from storage.fred_client import fetch_all_indicators
        try:
            inds, ts = await run.io_bound(fetch_all_indicators)
        except Exception as exc:
            inds, ts = [], f"Error: {exc}"
        c = fred_ref.get("container")
        if c is not None:
            c.clear()
            with c:
                render_fred_panel(inds, ts)

    asyncio.ensure_future(_load_fred())

    with ui.tabs().classes("w-full") as tabs:
        tab_macro  = ui.tab("Macro Views")
        tab_asset  = ui.tab("Asset Class Views")
        tab_quant  = ui.tab("Quant Development")
        tab_recon  = ui.tab("Weekly Reconciliation")
        tab_log    = ui.tab("Change Log")
        tab_fred   = ui.tab("Economic Data")

    with ui.tab_panels(tabs, value=tab_macro).classes("w-full"):
        with ui.tab_panel(tab_macro):
            render_briefing_strip(s, save_indicator)
            render_macro_views(s, save_indicator, log_change=log_change)

        with ui.tab_panel(tab_asset):
            render_asset_views(s, save_indicator)

        with ui.tab_panel(tab_quant):
            render_quant_tracker(s, save_indicator)

        with ui.tab_panel(tab_recon):
            render_reconciliation(s, save_indicator)

        with ui.tab_panel(tab_log):
            render_view_change_log(s, save_indicator)

        with ui.tab_panel(tab_fred):
            with ui.element("div").style("width:100%;") as _fred_c:
                with ui.column().style("align-items:center; padding:4rem; gap:0.75rem;"):
                    ui.spinner("audio", size="2rem", color="#2dd4bf")
                    ui.label("Fetching FRED data…").style(
                        "color:var(--text-muted); font-size:0.8rem; "
                        "letter-spacing:0.08em; font-family:'IBM Plex Mono',monospace;"
                    )
            fred_ref["container"] = _fred_c


ui.run(title="MacroQuant Ledger", port=8080, reload=False, host="0.0.0.0")
