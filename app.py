from __future__ import annotations
import asyncio
import os
from nicegui import ui, app as ni_app
from storage.persistence import load_state, save_state, import_state, STATE_FILE
from components.status_bar import render_status_bar
from components.macro_views import render_macro_views
from components.reconciliation import render_reconciliation
from components.asset_views import render_asset_views
from components.fred_panel import render_fred_panel
from components.trades import render_trades
from components.attribution import render_attribution
from components.interview_practice import render_interview_practice
from components.topic_views import render_topic_views
from components.today import render_today
from export.excel import generate_excel
from storage.user_settings import obsidian_export_path, save_obsidian_export_path, obsidian_views_folder, save_obsidian_views_folder
from storage.topic_view_sync import sync_is_enabled, set_sync_enabled
from services.interview_llm import available as interview_llm_available
from services.interview_speech import register_interview_speech_routes

register_interview_speech_routes(ni_app)

_BULL_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M18 16c-1 2-3 3-6 3s-5-1-6-3c-1-2-1-4 0-6 1-2 2-3 3-4 0-1 1-2 2-2 1 0 2 1 2 2 0 1 1 2 2 3 1 2 1 4 0 6zM6 8l-2 2M22 8l-2 2" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>'
_BEAR_SVG = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><circle cx="6" cy="7" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="12" cy="15" r="6"/></svg>'

# ── CSS ────────────────────────────────────────────────────────────────────────
CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap');

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
    --font-ui:       'Inter', system-ui, sans-serif;
    --font-data:     'IBM Plex Mono', monospace;
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
    font-family: var(--font-ui) !important;
    transition: background 0.2s, color 0.2s;
}

/* ── Header ── */
.app-header {
    background: var(--bg-primary);
    border-bottom: none;
    padding: 0.85rem 1.5rem 0.85rem 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    position: relative;
}
.app-header::after {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent 0%, var(--accent) 30%, var(--accent) 70%, transparent 100%);
    opacity: 0.35;
}
.app-title-block { flex-shrink: 0; min-width: 0; }
.header-brand {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}
.mq-monogram {
    display: flex;
    align-items: baseline;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 700;
    font-size: 2rem;
    line-height: 1;
    letter-spacing: -0.05em;
}
.mq-letter {
    display: inline-block;
    background: linear-gradient(135deg, var(--accent) 0%, #4ade80 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.mq-m {
    transform: translateY(-2px);
}
.mq-q {
    transform: translateY(2px);
    margin-left: -2px;
}
@keyframes title-glow {
    from { text-shadow: 0 0 6px #2dd4bf00; }
    to   { text-shadow: 0 0 14px #2dd4bf35; }
}
@keyframes title-glow-light {
    from { text-shadow: 0 0 4px #0f766e00; }
    to   { text-shadow: 0 0 10px #0f766e20; }
}
.app-title {
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--accent) !important;
    letter-spacing: 0.12em;
    font-family: 'IBM Plex Mono', monospace !important;
    white-space: nowrap;
    animation: title-glow 3s ease-in-out infinite alternate;
}
body.light-mode .app-title {
    animation-name: title-glow-light;
}
.app-subtitle {
    font-size: 0.68rem;
    color: var(--text-muted) !important;
    letter-spacing: 0.08em;
    margin-top: 2px;
    font-family: 'IBM Plex Mono', monospace !important;
    white-space: nowrap;
}
.header-clock {
    font-size: 0.6rem;
    color: var(--text-faint) !important;
    letter-spacing: 0.06em;
    margin-top: 1px;
    font-family: 'IBM Plex Mono', monospace !important;
    white-space: nowrap;
}
.header-clock-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
}
@keyframes live-pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 4px #4ade8060; }
    50%      { opacity: 0.4; box-shadow: 0 0 8px #4ade8020; }
}
.live-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #4ade80;
    animation: live-pulse 2s ease-in-out infinite;
    flex-shrink: 0;
}
body.light-mode .live-dot {
    background: #16a34a;
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
    gap: 0.7rem;
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
.status-summary-action {
    appearance:none; border:0; background:transparent; color:var(--text-primary);
    display:flex; align-items:center; gap:0.45rem; padding:0.22rem 0.35rem;
    border-radius:5px; font:inherit; cursor:pointer;
}
.status-summary-action:hover { background:var(--bg-hover); }
.status-summary-dot {
    width:7px; height:7px; border-radius:50%; box-shadow:0 0 6px currentColor;
}
.status-summary-label { font-size:0.72rem; font-weight:600; }
.status-summary-value {
    font-family:var(--font-data) !important; font-size:0.68rem; font-weight:700;
}
.status-divider { width:1px; height:16px; background:var(--border-strong); }

/* ── Quiet save state ── */
.save-status {
    color:var(--text-faint) !important; font-family:var(--font-data) !important;
    font-size:0.65rem; white-space:nowrap; transition:color 0.2s;
}
.save-status.is-fresh { color:#4ade80 !important; }

/* ── Tabs ── */
.q-tabs {
    background: var(--tab-bg) !important;
    border-bottom: 1px solid var(--border) !important;
}
.q-tab {
    color: var(--text-muted) !important;
    font-family: var(--font-ui) !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
}
.secondary-tabs {
    border:1px solid var(--border) !important; border-radius:7px;
    margin-bottom:1rem; padding:3px; background:var(--bg-card) !important;
}
.secondary-tabs .q-tab {
    min-height:34px !important; border-radius:5px; font-size:0.72rem !important;
    letter-spacing:0.04em !important; text-transform:none !important;
}
.secondary-tabs .q-tab--active { background:var(--accent-glow) !important; }
.secondary-tabs .q-tab-indicator { display:none !important; }
.secondary-panels > .q-panel > .q-tab-panel,
.secondary-panels .q-tab-panel { padding:0 !important; }
.q-tab--active { color: var(--accent) !important; }
.q-tab:hover:not(.q-tab--active) {
    color: var(--text-primary) !important;
}
.q-tab-indicator { background: var(--accent) !important; }
.q-tab-panels { background: var(--bg-primary) !important; }
.q-tab-panel {
    padding: 1.5rem 2rem !important;
    background: var(--bg-primary) !important;
    /* NiceGUI's .nicegui-tab-panel uses align-items:flex-start, which shrink-wraps
       width:auto children (e.g. CSS grid rows). Stretch so full-width tiles/grids work. */
    align-items: stretch !important;
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
    font-family: var(--font-ui) !important;
    font-size: 0.9rem !important;
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
.asset-score-control { display:flex; gap:3px; align-items:center; flex-shrink:0; }
.asset-score-button {
    min-width:30px !important; width:30px !important; min-height:30px !important;
    padding:0 !important; background:var(--bg-input) !important;
    color:var(--text-muted) !important; border:1px solid var(--border) !important;
    border-radius:5px !important; box-shadow:none !important;
    font:700 0.74rem var(--font-data) !important;
}
.asset-score-control.compact .asset-score-button {
    min-width:23px !important; width:23px !important; min-height:27px !important;
}
.asset-score-button:hover { border-color:var(--accent) !important; color:var(--text-primary) !important; }
.asset-score-button.is-active { transform:translateY(-1px); box-shadow:0 3px 10px #0003 !important; }

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

/* ── Today ── */
.today-hero {
    width:100%; padding:0.7rem 0; margin-bottom:0.6rem;
    display:flex; align-items:center; justify-content:space-between; gap:0.75rem; flex-wrap:wrap;
}
.today-eyebrow {
    color:var(--accent) !important; font-family:var(--font-data) !important;
    font-size:0.62rem; font-weight:700; letter-spacing:0.12em; text-transform:uppercase;
}
.today-title {
    color:var(--text-primary) !important; font-size:1rem;
    font-weight:700; letter-spacing:-0.015em; margin-top:0.1rem;
}
.today-copy {
    color:var(--text-muted) !important; font-size:0.88rem; line-height:1.6;
    max-width:720px; margin-top:0.35rem;
}
.today-metric-grid {
    display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0.5rem; width:100%;
}
.today-metric-card {
    appearance:none; text-align:left; width:100%; min-height:86px; padding:0.65rem 0.75rem;
    color:var(--text-primary); background:var(--bg-card); border:1px solid var(--border);
    border-radius:8px; cursor:pointer; transition:transform .15s,border-color .15s,box-shadow .15s;
}
.today-metric-card:hover {
    transform:translateY(-2px); border-color:var(--accent);
    box-shadow:0 8px 24px var(--accent-glow);
}
.today-metric-topline { display:flex; align-items:flex-start; justify-content:space-between; }
.today-metric-value {
    color:var(--text-primary) !important; font:700 1.15rem var(--font-data) !important;
}
.today-metric-arrow { color:var(--text-faint) !important; transition:color .15s,transform .15s; }
.today-metric-card:hover .today-metric-arrow { color:var(--accent) !important; transform:translateX(2px); }
.today-metric-label { color:var(--text-primary) !important; font-size:0.72rem; font-weight:600; margin-top:0.28rem; }
.today-metric-detail { color:var(--text-muted) !important; font-size:0.64rem; margin-top:0.1rem; }
.today-actions { gap:0.55rem; margin:0; flex-wrap:wrap; }
.today-top-of-mind { width:100%; display:flex; align-items:flex-start; gap:0.65rem; padding:0.45rem 0.55rem; margin-bottom:0.45rem; border:1px solid var(--border); border-radius:6px; background:var(--bg-card); }
.today-top-of-mind-label { color:var(--accent) !important; font:700 0.6rem var(--font-data) !important; letter-spacing:0.12em; padding-top:0.45rem; }
.today-top-of-mind-input { flex:1; min-width:0; }
.today-top-of-mind-input textarea { min-height:96px !important; height:auto !important; padding:0.4rem 0.55rem !important; line-height:1.35 !important; resize:vertical !important; }
.export-btn {
    background: var(--accent) !important;
    color: #fff !important;
    font-weight: 700 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    border-radius: 4px !important;
    padding: 0 1rem !important;
    box-shadow: none !important;
    white-space: nowrap !important;
    transition: transform 0.15s, box-shadow 0.15s, opacity 0.15s !important;
}
.export-btn:hover {
    opacity: 0.88 !important;
    transform: translateY(-1px);
    box-shadow: 0 3px 12px #2dd4bf25;
}
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
    transition: transform 0.15s, color 0.15s, border-color 0.15s !important;
}
.theme-btn:hover {
    color: var(--accent) !important;
    border-color: var(--accent) !important;
    transform: scale(1.12);
}
.menu-btn {
    background: transparent !important;
    color: var(--text-muted) !important;
    border: 1px solid var(--border) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    min-width: 2.2rem !important;
    padding: 0 0.6rem !important;
    letter-spacing: 0.15em !important;
    font-size: 0.85rem !important;
}
.menu-btn:hover {
    color: var(--accent) !important;
    border-color: var(--accent) !important;
}
.overflow-menu {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: 6px !important;
    min-width: 172px !important;
}
.overflow-menu .q-item {
    color: var(--text-primary) !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
    padding: 0.55rem 1rem !important;
    min-height: unset !important;
    letter-spacing: 0.04em !important;
}
.overflow-menu .q-item:hover { background: var(--bg-hover) !important; }
.overflow-menu .q-separator { background: var(--border) !important; margin: 0.2rem 0 !important; }
.overflow-menu .menu-item-danger .q-item__label { color: #f87171 !important; }

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
    .header-clock { display: none; }
    .header-actions { gap: 0.3rem; flex-wrap: wrap; }
    .save-status { display:none; }
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
    .today-metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }

}

@media (min-width:641px) and (max-width:980px) {
    .today-metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
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


@ui.page("/")
def index():
    dark = ui.dark_mode()
    dark.enable()
    ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    ui.add_head_html(f'<style id="mq-main-css">{CUSTOM_CSS}</style>')

    s = get_state()

    saved_ref = {"el": None}
    status_container = {"el": None}
    navigation = {"primary": {}, "secondary": {}}
    practice_bridge = {"open": None}
    views_bridge = {"open": None}

    def navigate(section: str, destination: str | None = None):
        primary = navigation["primary"].get(section)
        if primary is not None:
            navigation["tabs"].set_value(primary)
        if destination is not None:
            secondary = navigation["secondary"].get(section)
            target = navigation["secondary"].get(destination)
            if secondary is not None and target is not None:
                secondary.set_value(target)

    def practice_views(view_ids, style="Deliver"):
        opener = practice_bridge.get("open")
        if opener:
            opener(view_ids, style)
        navigate("practice")

    def review_view(view_id):
        opener = views_bridge.get("open")
        if opener:
            opener(view_id)
        navigate("views", "my_views")

    def refresh_status():
        if status_container["el"] is not None:
            status_container["el"].clear()
            with status_container["el"]:
                render_status_bar(
                    s,
                    on_views_click=lambda: navigate("views", "my_views"),
                    on_reconciliation_click=lambda: navigate("review", "weekly"),
                )

    def save_indicator():
        if saved_ref["el"] is not None:
            saved_ref["el"].set_text("Saved just now")
            saved_ref["el"].classes(add="is-fresh")
        refresh_status()

    # ── Header ────────────────────────────────────────────────────────────────
    with ui.element("div").classes("app-header"):
        with ui.element("div").classes("header-brand"):
            with ui.element("div").classes("mq-monogram"):
                ui.label("M").classes("mq-letter mq-m")
                ui.label("Q").classes("mq-letter mq-q")
            with ui.element("div").classes("app-title-block"):
                ui.label("MACROQUANT LEDGER").classes("app-title")
                with ui.element("div").classes("header-clock-wrap"):
                    ui.element("span").classes("live-dot")
                    ui.label("").classes("header-clock")

        with ui.element("div").classes("header-actions"):
            saved_ref["el"] = ui.label("All changes saved").classes("save-status")
            # ── Theme toggle ──────────────────────────────────────────────────
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

            def open_settings():
                with ui.dialog() as dialog, ui.card().style(
                    "background:var(--bg-card); color:var(--text-primary); "
                    "font-family:'IBM Plex Mono',monospace; width:min(620px,92vw); padding:1.5rem;"
                ):
                    ui.label("Settings").style(
                        "font-size:1rem; font-weight:700; color:var(--accent); margin-bottom:0.3rem;"
                    )
                    ui.label(
                        "Obsidian export writes notes one-way. Obsidian Views sync is a separate, "
                        "optional bidirectional folder for My Views. Settings are stored locally in "
                        "data/user_settings.json."
                    ).style(
                        "color:var(--text-muted); font-size:0.78rem; line-height:1.55; margin-bottom:0.8rem;"
                    )
                    ui.label("INTEGRATIONS").classes("field-label")
                    with ui.row().style("gap:0.55rem;flex-wrap:wrap;margin-bottom:0.8rem;"):
                        interview_ready = interview_llm_available()
                        ui.label(
                            f"Interview API · {'ready' if interview_ready else 'key missing'}"
                        ).style(
                            f"color:{'#4ade80' if interview_ready else '#f59e0b'};font-size:0.7rem;"
                            "border:1px solid var(--border);border-radius:4px;padding:3px 7px;"
                        )
                        fred_ready = bool((os.environ.get("FRED_API_KEY") or "").strip())
                        ui.label(
                            f"FRED · {'ready' if fred_ready else 'key missing'}"
                        ).style(
                            f"color:{'#4ade80' if fred_ready else 'var(--text-faint)'};font-size:0.7rem;"
                            "border:1px solid var(--border);border-radius:4px;padding:3px 7px;"
                        )
                    current_path = obsidian_export_path()
                    path_input = ui.input(
                        value=str(current_path) if current_path else "",
                        label="Obsidian export folder",
                        placeholder=r"C:\Path\To\ObsidianVault\MacroQuant",
                    ).classes("w-full dark-input")
                    current_views_folder = obsidian_views_folder()
                    views_folder_input = ui.input(
                        value=str(current_views_folder) if current_views_folder else "",
                        label="Obsidian Views folder (for My Views sync)",
                        placeholder=r"C:\Path\To\ObsidianVault\Views",
                    ).classes("w-full dark-input").style("margin-top:0.6rem")
                    sync_enabled = ui.checkbox(
                        "Enable bidirectional My Views sync",
                        value=sync_is_enabled(),
                    ).style("margin-top:0.5rem")
                    settings_status = ui.label("").style(
                        "font-size:0.72rem; color:#f87171; min-height:1rem; margin-top:0.4rem;"
                    )

                    def save_settings():
                        try:
                            save_obsidian_export_path(path_input.value or "")
                            if views_folder_input.value:
                                save_obsidian_views_folder(views_folder_input.value)
                            set_sync_enabled(sync_enabled.value)
                        except (ValueError, OSError) as exc:
                            settings_status.set_text(str(exc))
                            return
                        dialog.close()
                        ui.notify("Settings saved", type="positive", position="top")

                    with ui.row().style("justify-content:flex-end; gap:0.5rem; margin-top:0.8rem; width:100%;"):
                        ui.button("Cancel", on_click=dialog.close).classes("cancel-btn")
                        ui.button("Save Settings", on_click=save_settings).classes("submit-btn")
                dialog.open()

            # ── Overflow menu (rarely-used actions) ───────────────────────────
            def do_export_excel():
                path = generate_excel(s)
                ui.download(str(path))

            def do_export_json():
                ui.download(str(STATE_FILE), "macroquant_state.json")

            def do_import():
                with ui.dialog() as dialog, ui.card().style(
                    "background:var(--bg-card); color:var(--text-primary); "
                    "font-family:'IBM Plex Mono',monospace; min-width:min(380px,90vw); padding:1.5rem;"
                ):
                    ui.label("Import Macro State").style(
                        "font-size:1rem; font-weight:700; color:var(--accent); margin-bottom:0.5rem;"
                    )
                    ui.label(
                        "Upload a previously exported macroquant_state.json file. "
                        "Your current data will be replaced immediately."
                    ).style("color:var(--text-muted); font-size:0.8rem; margin-bottom:1.25rem; line-height:1.6;")
                    status_label = ui.label("").style("font-size:0.78rem; color:#f87171; min-height:1.2em;")

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

                    ui.upload(label="Choose state.json", auto_upload=True, on_upload=handle_upload).props("accept=.json").style("font-family:'IBM Plex Mono',monospace; font-size:0.8rem;")
                    with ui.row().style("gap:0.5rem; justify-content:flex-end; margin-top:1rem;"):
                        ui.button("Cancel", on_click=dialog.close).style(
                            "background:transparent; color:var(--text-muted); border:1px solid var(--border); box-shadow:none; font-family:'IBM Plex Mono',monospace;"
                        )
                dialog.open()

            def do_reset():
                with ui.dialog() as dialog, ui.card().style(
                    "background:var(--bg-card); color:var(--text-primary); "
                    "font-family:'IBM Plex Mono',monospace; min-width:min(340px,90vw); padding:1.5rem;"
                ):
                    ui.label("Reset Macro Data").style(
                        "font-size:1rem; font-weight:700; color:var(--accent); margin-bottom:0.5rem;"
                    )
                    ui.label(
                        "This will erase macro views, asset views, trades, and reconciliation history and restore defaults. "
                        "Practice sessions and app settings are not affected. This cannot be undone."
                    ).style("color:var(--text-muted); font-size:0.8rem; margin-bottom:1.25rem; line-height:1.6;")
                    with ui.row().style("gap:0.5rem; justify-content:flex-end;"):
                        ui.button("Cancel", on_click=dialog.close).style(
                            "background:transparent; color:var(--text-muted); border:1px solid var(--border); box-shadow:none; font-family:'IBM Plex Mono',monospace;"
                        )
                        def confirm_reset():
                            global state
                            from models.schema import default_state
                            state = default_state()
                            save_state(state)
                            dialog.close()
                            ui.navigate.reload()
                        ui.button("Yes, reset macro data", on_click=confirm_reset).style(
                            "background:#7f1d1d; color:#fca5a5; border:1px solid #991b1b; "
                            "box-shadow:none; font-family:'IBM Plex Mono',monospace; font-weight:700;"
                        )
                dialog.open()

            with ui.button("···").classes("menu-btn"):
                with ui.menu().classes("overflow-menu"):
                    ui.menu_item("Settings", on_click=open_settings)
                    ui.separator()
                    ui.menu_item("Export Excel", on_click=do_export_excel)
                    ui.menu_item("Export Macro JSON",  on_click=do_export_json)
                    ui.menu_item("Import Macro JSON",  on_click=do_import)
                    ui.separator()
                    ui.menu_item("Reset Macro Data", on_click=do_reset).classes("menu-item-danger")

    # ── Status Bar ────────────────────────────────────────────────────────────
    status_container["el"] = ui.element("div").style("width:100%;")
    with status_container["el"]:
        render_status_bar(
            s,
            on_views_click=lambda: navigate("views", "my_views"),
            on_reconciliation_click=lambda: navigate("review", "weekly"),
        )

    # ── Tabs ──────────────────────────────────────────────────────────────────
    # ── FRED data: load in background, update panel when ready ────────────────
    fred_ref = {"container": None}
    attribution_ref = {"container": None, "fred_data": None}

    async def _load_fred():
        from nicegui import run
        from storage.fred_client import fetch_all_indicators

        def refresh_if_alive(container, renderer) -> bool:
            """Render only while the page client that owns the container exists."""
            if container is None:
                return True
            try:
                container.clear()
                with container:
                    renderer()
            except RuntimeError as exc:
                if "client this element belongs to has been deleted" in str(exc):
                    return False
                raise
            return True

        try:
            inds, ts = await run.io_bound(fetch_all_indicators)
        except Exception as exc:
            inds, ts = [], f"Error: {exc}"
        c = fred_ref.get("container")
        if not refresh_if_alive(c, lambda: render_fred_panel(inds, ts)):
            return
        attribution_ref["fred_data"] = inds
        ac = attribution_ref.get("container")
        refresh_if_alive(ac, lambda: render_attribution(s, inds))

    asyncio.ensure_future(_load_fred())

    with ui.tabs().props('align="left" mobile-arrows outside-arrows').classes("w-full") as tabs:
        tab_today = ui.tab("Today")
        tab_views = ui.tab("Views")
        tab_research = ui.tab("Research")
        tab_review = ui.tab("Review")
        tab_interview = ui.tab("Practice")

    navigation["tabs"] = tabs
    navigation["primary"].update({
        "today": tab_today,
        "views": tab_views,
        "research": tab_research,
        "review": tab_review,
        "practice": tab_interview,
    })

    with ui.tab_panels(tabs, value=tab_today).classes("w-full"):
        with ui.tab_panel(tab_today):
            render_today(s, save_indicator, navigate)

        with ui.tab_panel(tab_views):
            with ui.tabs().props('align="left"').classes("secondary-tabs w-full") as views_tabs:
                view_topics = ui.tab("My Views")
                view_macro = ui.tab("Macro")
                view_assets = ui.tab("Assets")
                view_trades = ui.tab("Trades")
            navigation["secondary"]["views"] = views_tabs
            navigation["secondary"].update({
                "my_views": view_topics,
                "macro": view_macro,
                "assets": view_assets,
                "trades": view_trades,
            })
            with ui.tab_panels(views_tabs, value=view_topics).classes("secondary-panels w-full"):
                with ui.tab_panel(view_topics):
                    render_topic_views(s, save_indicator, practice_views, views_bridge)
                with ui.tab_panel(view_macro):
                    render_macro_views(s, save_indicator)
                with ui.tab_panel(view_assets):
                    render_asset_views(s, save_indicator)
                with ui.tab_panel(view_trades):
                    render_trades(s, save_indicator)

        with ui.tab_panel(tab_research):
            with ui.tabs().props('align="left"').classes("secondary-tabs w-full") as research_tabs:
                research_data = ui.tab("Economic Data")
            navigation["secondary"]["research"] = research_tabs
            navigation["secondary"].update({
                "data": research_data,
            })
            with ui.tab_panels(research_tabs, value=research_data).classes("secondary-panels w-full"):
                with ui.tab_panel(research_data):
                    with ui.element("div").style("width:100%;") as _fred_c:
                        with ui.column().style("align-items:center; padding:4rem; gap:0.75rem;"):
                            ui.spinner("audio", size="2rem", color="#2dd4bf")
                            ui.label("Fetching FRED data…").style(
                                "color:var(--text-muted); font-size:0.8rem; "
                                "letter-spacing:0.08em; font-family:'IBM Plex Mono',monospace;"
                            )
                    fred_ref["container"] = _fred_c

        with ui.tab_panel(tab_review):
            with ui.tabs().props('align="left"').classes("secondary-tabs w-full") as review_tabs:
                review_weekly = ui.tab("Weekly Review")
                review_attribution = ui.tab("Attribution")
            navigation["secondary"]["review"] = review_tabs
            navigation["secondary"].update({
                "weekly": review_weekly,
                "attribution": review_attribution,
            })
            with ui.tab_panels(review_tabs, value=review_weekly).classes("secondary-panels w-full"):
                with ui.tab_panel(review_weekly):
                    render_reconciliation(s, save_indicator)
                with ui.tab_panel(review_attribution):
                    with ui.element("div").style("width:100%;") as _attr_c:
                        render_attribution(s, None)
                    attribution_ref["container"] = _attr_c

        with ui.tab_panel(tab_interview):
            render_interview_practice(s, practice_bridge, review_view)

    # ── Live clock ──────────────────────────────────────────────────────────
    ui.run_javascript("""
        function updateClock() {
            const el = document.querySelector('.header-clock');
            if (!el) return;
            const now = new Date();
            const date = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
            const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
            el.textContent = date + ' \\u00b7 ' + time;
        }
        updateClock();
        setInterval(updateClock, 10000);
    """)


ui.run(
    title="MacroQuant Ledger",
    port=int(os.environ.get("MQLEDGER_PORT", "8080")),
    reload=False,
    host="0.0.0.0",
    show=False,
)
