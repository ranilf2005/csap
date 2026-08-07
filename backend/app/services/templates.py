"""Builds the dynamic Excel workbook from a plugin's template_spec()."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3B57")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def build_workbook(spec: dict[str, list[str]], product: str, product_version: str | None) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)

    info = wb.create_sheet("README")
    info.append(["Cisco Security Automation Platform - change template"])
    info.append(["Product", product])
    info.append(["Detected version", product_version or "unknown"])
    info.append([])
    info.append(["Set the 'action' column to create, update or delete. Blank rows are ignored."])
    info.column_dimensions["A"].width = 30
    info.column_dimensions["B"].width = 60
    info["A1"].font = Font(bold=True, size=14)

    for sheet_name, headers in spec.items():
        ws = wb.create_sheet(sheet_name[:31])
        ws.append(headers)
        for col, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(col)].width = max(14, len(header) + 4)
        ws.freeze_panes = "A2"

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
