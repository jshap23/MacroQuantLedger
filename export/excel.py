from __future__ import annotations
from datetime import datetime
from pathlib import Path
import openpyxl
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side
)
from openpyxl.utils import get_column_letter
from models.schema import AppState

# ── Palette ────────────────────────────────────────────────────────────────────
NAVY     = "1B2A4A"
GOLD     = "C9A84C"
WHITE    = "FFFFFF"
CREAM    = "FDF8F0"
LIGHT_BG = "F5F5F5"

def _header_font():  return Font(name="Calibri", bold=True, color=WHITE, size=11)
def _title_font():   return Font(name="Calibri", bold=True, color=GOLD, size=13)
def _body_font():    return Font(name="Calibri", size=10)
def _navy_fill():    return PatternFill("solid", fgColor=NAVY)
def _cream_fill():   return PatternFill("solid", fgColor=CREAM)
def _gold_fill():    return PatternFill("solid", fgColor=GOLD)

def _border():
    thin = Side(style="thin", color="CCCCCC")
    return Border(left=thin, right=thin, top=thin, bottom=thin)

def _set_col_widths(ws, widths: list[int]):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _write_headers(ws, row: int, headers: list[str]):
    for col, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=h)
        cell.font = _header_font()
        cell.fill = _navy_fill()
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _border()
    ws.row_dimensions[row].height = 20


def _write_row(ws, row: int, values: list, alt: bool = False):
    fill = _cream_fill() if alt else PatternFill("solid", fgColor="FFFFFF")
    for col, v in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=v)
        cell.font = _body_font()
        cell.fill = fill
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        cell.border = _border()
    ws.row_dimensions[row].height = 40


def _section_title(ws, row: int, title: str, ncols: int):
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = Font(name="Calibri", bold=True, color=WHITE, size=12)
    cell.fill = PatternFill("solid", fgColor=GOLD)
    cell.alignment = Alignment(horizontal="left", vertical="center")
    if ncols > 1:
        ws.merge_cells(
            start_row=row, start_column=1,
            end_row=row, end_column=ncols
        )
    ws.row_dimensions[row].height = 22


def _fmt_dt(dt) -> str:
    if dt is None:
        return ""
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d")
    return str(dt)


# ── Sheet builders ─────────────────────────────────────────────────────────────

def _sheet_macro_views(wb, state: AppState):
    ws = wb.create_sheet("Macro Views")
    headers = ["Variable", "Directional Lean", "Signal 1", "Signal 2", "Signal 3",
               "The Counter", "Conviction", "Flag", "Last Touched"]
    _write_headers(ws, 1, headers)
    ws.freeze_panes = "A2"

    for i, v in enumerate(state.macro_views):
        _write_row(ws, i + 2, [
            v.name,
            v.lean,
            v.signals[0] if len(v.signals) > 0 else "",
            v.signals[1] if len(v.signals) > 1 else "",
            v.signals[2] if len(v.signals) > 2 else "",
            v.counter,
            v.conviction,
            v.flag,
            _fmt_dt(v.last_touched),
        ], alt=bool(i % 2))

    if state.macro_notes:
        row = len(state.macro_views) + 3
        ws.cell(row=row, column=1, value="NOTES").font = Font(name="Calibri", bold=True, color=GOLD, size=11)
        row += 1
        cell = ws.cell(row=row, column=1, value=state.macro_notes)
        cell.font = _body_font()
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(headers))
        ws.row_dimensions[row].height = 80

    _set_col_widths(ws, [22, 40, 30, 30, 30, 35, 12, 12, 14])


def _sheet_implication_map(wb, state: AppState):
    ws = wb.create_sheet("Implication Map")
    headers = ["Macro Variable", "Duration/Rates", "Credit", "Equities",
               "Vol (Rates+Eq)", "FX/USD", "Commodities"]
    _write_headers(ws, 1, headers)
    ws.freeze_panes = "A2"

    for i, v in enumerate(state.macro_views):
        row = i + 2
        cell = ws.cell(row=row, column=1, value=v.name)
        cell.font = Font(name="Calibri", bold=True, size=10)
        cell.fill = _cream_fill() if i % 2 else PatternFill("solid", fgColor="FFFFFF")
        cell.border = _border()
        for col in range(2, 8):
            c = ws.cell(row=row, column=col, value="")
            c.fill = _cream_fill() if i % 2 else PatternFill("solid", fgColor="FFFFFF")
            c.border = _border()
        ws.row_dimensions[row].height = 45

    _set_col_widths(ws, [22, 25, 25, 25, 22, 22, 22])


def _sheet_quant_tracker(wb, state: AppState):
    ws = wb.create_sheet("Quant Tracker")
    qt = state.quant_tracker

    row = 1
    # Projects
    _section_title(ws, row, "ACTIVE RESEARCH PROJECTS", 5)
    row += 1
    _write_headers(ws, row, ["Project", "Current Status", "Next Step", "Priority", "Last Touched"])
    ws.freeze_panes = f"A{row + 1}"
    row += 1
    for i, p in enumerate(qt.projects):
        _write_row(ws, row, [p.name, p.status, p.next_step, p.priority, _fmt_dt(p.last_touched)], alt=bool(i % 2))
        row += 1

    row += 1
    # Skills
    _section_title(ws, row, "TECHNICAL SKILLS INVENTORY", 5)
    row += 1
    _write_headers(ws, row, ["Skill/Method", "Level", "Building", "Interview Relevance", "Last Touched"])
    row += 1
    for i, s in enumerate(qt.skills):
        _write_row(ws, row, [s.name, s.level, s.building, s.interview_relevance, _fmt_dt(s.last_touched)], alt=bool(i % 2))
        row += 1

    row += 1
    # Readiness
    _section_title(ws, row, "INTERVIEW READINESS", 5)
    row += 1
    _write_headers(ws, row, ["Topic Area", "Strength/Gap", "Evidence", "Action This Week", "Last Touched"])
    row += 1
    for i, r in enumerate(qt.readiness):
        _write_row(ws, row, [r.area, r.strength, r.evidence, r.action, _fmt_dt(r.last_touched)], alt=bool(i % 2))
        row += 1

    _set_col_widths(ws, [25, 15, 40, 30, 14])


def _sheet_reconciliation(wb, state: AppState):
    ws = wb.create_sheet("Reconciliation")
    headers = ["Week Of", "Macro Scan", "Quant Check", "% Macro", "% Quant", "% Other", "Synthesis"]
    _write_headers(ws, 1, headers)
    ws.freeze_panes = "A2"

    for i, r in enumerate(state.reconciliations):
        _write_row(ws, i + 2, [
            r.date.strftime("%Y-%m-%d") if r.date else "",
            r.macro_scan,
            r.quant_check,
            r.time_macro,
            r.time_quant,
            r.time_other,
            r.synthesis,
        ], alt=bool(i % 2))

    _set_col_widths(ws, [14, 50, 50, 10, 10, 10, 50])


# ── Public entry point ─────────────────────────────────────────────────────────

def generate_excel(state: AppState) -> Path:
    wb = openpyxl.Workbook()
    # Remove default sheet
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    _sheet_macro_views(wb, state)
    _sheet_implication_map(wb, state)
    _sheet_quant_tracker(wb, state)
    _sheet_reconciliation(wb, state)

    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"macroquant_ledger_{date_str}.xlsx"
    wb.save(out_path)
    return out_path
