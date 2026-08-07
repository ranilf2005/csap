"""Builds the dynamic Excel workbook from a plugin's template_spec() and current config."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3B57")
REFERENCE_FILL = PatternFill("solid", fgColor="6B7A8C")
HEADER_FONT = Font(color="FFFFFF", bold=True)
MAX_ROWS_PER_SHEET = 10_000


def build_workbook(
    spec: dict[str, list[str]],
    product: str,
    product_version: str | None,
    existing: dict[str, list[dict[str, Any]]] | None = None,
    reference_sheets: set[str] | None = None,
) -> bytes:
    existing = existing or {}
    reference_sheets = reference_sheets or set()

    wb = Workbook()
    wb.remove(wb.active)
    _write_readme(wb, spec, existing, product, product_version, reference_sheets)

    for sheet_name, headers in spec.items():
        ws = wb.create_sheet(sheet_name[:31])
        ws.append(headers)

        is_reference = sheet_name in reference_sheets
        for col, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col)
            cell.fill = REFERENCE_FILL if is_reference else HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(col)].width = max(14, len(header) + 4)

        for row in (existing.get(sheet_name) or [])[:MAX_ROWS_PER_SHEET]:
            ws.append([_cell(row.get(header)) for header in headers])

        ws.freeze_panes = "A2"
        if ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


FINDING_HEADERS = ["Severity", "Sheet", "Row", "Column", "What is wrong", "What you should do"]
SEVERITY_FILL = {
    "error": PatternFill("solid", fgColor="FDECEC"),
    "warning": PatternFill("solid", fgColor="FFF5E0"),
    "info": PatternFill("solid", fgColor="E8F1FD"),
}
SEVERITY_FONT = {
    "error": Font(color="A01B1B", bold=True),
    "warning": Font(color="8A5B00", bold=True),
    "info": Font(color="144D9C", bold=True),
}
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def build_findings_workbook(
    issues: list[dict[str, Any]],
    filename: str,
    system_name: str,
    counts: dict[str, int],
) -> bytes:
    """One row per finding, with the remediation spelled out, ready to hand to whoever fixes it."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Findings"

    ws.append([f"Validation findings for {filename}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"System: {system_name}"])
    ws.append(
        [
            f"Errors: {counts.get('errors', 0)}    "
            f"Warnings: {counts.get('warnings', 0)}    "
            f"Planned changes: {counts.get('changes', 0)}"
        ]
    )
    ws.append(["Errors block deployment. Warnings do not, but read them - a warning usually"])
    ws.append(["means a row you edited will be ignored."])
    ws.append([])

    header_row = ws.max_row + 1
    ws.append(FINDING_HEADERS)
    for col in range(1, len(FINDING_HEADERS) + 1):
        cell = ws.cell(row=header_row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    ordered = sorted(
        issues,
        key=lambda i: (
            SEVERITY_ORDER.get(str(i.get("severity")), 9),
            str(i.get("sheet") or ""),
            i.get("row") or 0,
        ),
    )
    for issue in ordered:
        severity = str(issue.get("severity") or "info")
        ws.append(
            [
                severity,
                issue.get("sheet") or "-",
                issue.get("row") or "",
                issue.get("field") or "",
                issue.get("message") or "",
                issue.get("remediation") or "",
            ]
        )
        cell = ws.cell(row=ws.max_row, column=1)
        cell.fill = SEVERITY_FILL.get(severity, SEVERITY_FILL["info"])
        cell.font = SEVERITY_FONT.get(severity, SEVERITY_FONT["info"])

    if not ordered:
        ws.append(["info", "-", "", "", "No issues found.", "Nothing to do - this workbook is ready."])

    for column, width in zip("ABCDEF", (12, 18, 8, 14, 62, 72), strict=True):
        ws.column_dimensions[column].width = width
    for row in ws.iter_rows(min_row=header_row + 1):
        for cell in row[4:6]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.auto_filter.ref = f"A{header_row}:F{ws.max_row}"

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _write_readme(
    wb: Workbook,
    spec: dict[str, list[str]],
    existing: dict[str, list[dict[str, Any]]],
    product: str,
    product_version: str | None,
    reference_sheets: set[str],
) -> None:
    ws = wb.create_sheet("README")
    ws.append(["Cisco Security Automation Platform - change template"])
    ws["A1"].font = Font(bold=True, size=14)

    ws.append([])
    ws.append(["Product", product])
    ws.append(["Detected version", product_version or "unknown"])
    ws.append([])

    for line in (
        "This workbook already contains your current configuration, one row per object.",
        "",
        "To change something, set the 'action' column on that row:",
        "    create   add a new object (use a new row)",
        "    update   change the object named on that row",
        "    delete   remove the object named on that row",
        "",
        "Rows with a blank 'action' are ignored, so you can leave the rest untouched.",
        "Column order does not matter. Extra sheets are ignored.",
    ):
        ws.append([line])

    ws.append([])
    ws.append(["Sheet", "Rows", "Deployable"])
    header_row = ws.max_row
    for col in range(1, 4):
        cell = ws.cell(row=header_row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    for sheet_name in spec:
        ws.append(
            [
                sheet_name,
                len(existing.get(sheet_name) or []),
                "reference only" if sheet_name in reference_sheets else "yes",
            ]
        )

    truncated = [name for name, rows in existing.items() if len(rows) > MAX_ROWS_PER_SHEET]
    if truncated:
        ws.append([])
        ws.append([f"Truncated to {MAX_ROWS_PER_SHEET} rows: {', '.join(truncated)}"])

    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 18
