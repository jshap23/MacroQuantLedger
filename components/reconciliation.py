from __future__ import annotations
from datetime import datetime, timezone
from nicegui import ui
from models.schema import AppState, Reconciliation
from storage.persistence import save_state


def render_reconciliation(state: AppState, save_indicator):
    def save():
        save_state(state)
        save_indicator()

    container = ui.element("div").style("width:100%;")

    def refresh():
        container.clear()
        with container:
            _render_content(state, save, refresh)

    refresh()


def _render_content(state: AppState, save, refresh):
    # ── Current Quant Focus ────────────────────────────────────────────────────
    ui.label("CURRENT QUANT FOCUS").classes("section-header")
    focus_input = ui.input(
        value=state.quant_focus,
        placeholder="What are you building right now?"
    ).classes("w-full dark-input")
    focus_input.on("blur", lambda _: (
        setattr(state, "quant_focus", focus_input.value), save()
    ))

    next_input = ui.input(
        value=state.quant_focus_next,
        placeholder="Where is it headed?"
    ).classes("w-full dark-input").style("margin-top:0.4rem; margin-bottom:1.75rem;")
    next_input.on("blur", lambda _: (
        setattr(state, "quant_focus_next", next_input.value), save()
    ))

    form_visible = {"v": False}
    form_container = ui.element("div")

    # Toggle button
    start_btn = ui.button(
        "+ Start Weekly Reconciliation",
        on_click=lambda: _show_form(form_container, form_visible, start_btn, state, save, refresh)
    ).classes("add-btn").style("margin-bottom:1.5rem; font-size:1rem; padding:0.75rem 1.5rem;")

    with form_container:
        pass  # populated on click

    # History
    if state.reconciliations:
        ui.label("HISTORY").classes("section-header").style("margin-top:1rem;")
        for rec in state.reconciliations:
            _history_card(rec, state, save, refresh)


def _show_form(form_container, form_visible, start_btn, state: AppState, save, refresh):
    if form_visible["v"]:
        return
    form_visible["v"] = True
    start_btn.set_visibility(False)

    form_container.clear()
    with form_container:
        now = datetime.now()
        date_str = now.strftime("%b %d, %Y")

        with ui.element("div").classes("recon-form-card"):
            ui.label(f"Weekly Reconciliation — {date_str}").style(
                "font-size:1.1rem; font-weight:700; color:#c9a84c; margin-bottom:1rem;"
            )

            ui.label("MACRO INVENTORY SCAN").classes("field-label")
            macro_scan = ui.textarea(
                placeholder="What changed? What's stale? What should have changed but didn't?"
            ).classes("full-width dark-input")

            ui.label("QUANT DEVELOPMENT CHECK").classes("field-label")
            quant_check = ui.textarea(
                placeholder="Did you build or code anything? Or just consume?"
            ).classes("full-width dark-input")

            ui.label("TIME ALLOCATION (% of discretionary hours)").classes("field-label")
            submit_ref = [None]

            with ui.row().style("gap:1rem; align-items:center; flex-wrap:wrap;"):
                macro_pct = ui.number(label="Macro", value=33, min=0, max=100).classes("dark-input").style("width:100px;")
                quant_pct = ui.number(label="Quant Dev", value=33, min=0, max=100).classes("dark-input").style("width:100px;")
                other_pct = ui.number(label="Other", value=34, min=0, max=100).classes("dark-input").style("width:100px;")
                total_label = ui.label("Total: 100% ✓").style("color:#4ade80; font-size:0.85rem;")

            def update_total():
                total = int(macro_pct.value or 0) + int(quant_pct.value or 0) + int(other_pct.value or 0)
                if total == 100:
                    total_label.set_text("Total: 100% ✓")
                    total_label.style("color:#4ade80; font-size:0.85rem;")
                    if submit_ref[0]:
                        submit_ref[0].enable()
                else:
                    total_label.set_text(f"Total: {total}% — must equal 100")
                    total_label.style("color:#f87171; font-size:0.85rem;")
                    if submit_ref[0]:
                        submit_ref[0].disable()

            macro_pct.on("update:model-value", lambda _: update_total())
            quant_pct.on("update:model-value", lambda _: update_total())
            other_pct.on("update:model-value", lambda _: update_total())

            ui.label("SYNTHESIS — ONE SENTENCE").classes("field-label")
            synthesis = ui.textarea(
                placeholder="One sentence: the tape + your positioning…"
            ).classes("full-width dark-input")

            with ui.row().style("gap:0.75rem; margin-top:1rem;"):
                def submit():
                    rec = Reconciliation(
                        date=datetime.now(tz=timezone.utc),
                        macro_scan=macro_scan.value,
                        quant_check=quant_check.value,
                        time_macro=int(macro_pct.value or 0),
                        time_quant=int(quant_pct.value or 0),
                        time_other=int(other_pct.value or 0),
                        synthesis=synthesis.value,
                    )
                    state.reconciliations.insert(0, rec)
                    if len(state.reconciliations) > 52:
                        state.reconciliations = state.reconciliations[:52]
                    save()
                    refresh()

                def cancel():
                    refresh()

                submit_btn = ui.button("Submit", on_click=submit).classes("submit-btn")
                submit_ref[0] = submit_btn
                ui.button("Cancel", on_click=cancel).classes("cancel-btn")


def _history_card(rec: Reconciliation, state: AppState, save, refresh):
    with ui.element("div").classes("recon-history-card"):
        with ui.row().style("align-items:center; justify-content:space-between;"):
            date_str = rec.date.strftime("%a, %b %d") if rec.date else "—"
            ui.label(date_str).style("font-weight:700; color:#c9a84c;")

            del_container = ui.element("div")
            confirming = {"v": False}

            def do_delete(r=rec):
                try:
                    state.reconciliations.remove(r)
                except ValueError:
                    pass
                save()
                refresh()

            def toggle_confirm():
                confirming["v"] = not confirming["v"]
                redraw_del()

            def redraw_del():
                del_container.clear()
                with del_container:
                    if confirming["v"]:
                        with ui.row().style("align-items:center; gap:0.3rem;"):
                            ui.label("Remove?").style(
                                "font-size:0.7rem; color:#f87171; "
                                "font-family:'IBM Plex Mono',monospace;"
                            )
                            ui.button("Yes", on_click=do_delete).style(
                                "background:#7f1d1d;color:#fca5a5;border:none;box-shadow:none;"
                                "font-size:0.7rem;padding:2px 8px;min-height:unset;border-radius:3px;"
                                "font-family:'IBM Plex Mono',monospace;"
                            )
                            ui.button("No", on_click=toggle_confirm).style(
                                "background:transparent;color:var(--text-muted);border:none;"
                                "box-shadow:none;font-size:0.7rem;padding:2px 8px;min-height:unset;"
                                "font-family:'IBM Plex Mono',monospace;"
                            )
                    else:
                        ui.button("✕", on_click=toggle_confirm).classes("remove-btn")

            redraw_del()

        if rec.synthesis:
            ui.label(rec.synthesis).style("font-style:italic; color:#aaa; margin:0.25rem 0;")

        ui.label(
            f"Macro {rec.time_macro}% · Quant {rec.time_quant}% · Other {rec.time_other}%"
        ).style("font-size:0.8rem; color:#888; margin-bottom:0.5rem;")

        if rec.macro_scan:
            ui.label("Macro scan:").classes("field-label").style("margin-top:0.5rem;")
            ui.label(rec.macro_scan).style("color:#ccc; font-size:0.85rem; white-space:pre-wrap;")

        if rec.quant_check:
            ui.label("Quant check:").classes("field-label").style("margin-top:0.5rem;")
            ui.label(rec.quant_check).style("color:#ccc; font-size:0.85rem; white-space:pre-wrap;")
