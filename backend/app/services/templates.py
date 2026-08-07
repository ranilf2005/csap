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
