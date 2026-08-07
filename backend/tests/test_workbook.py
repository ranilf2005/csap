from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services.workbook import WorkbookError, parse_workbook

SPEC = {
    "Hosts": ["action", "name", "value", "description"],
    "Networks": ["action", "name", "value", "description"],
}


def _write(tmp_path: Path, sheets: dict[str, list[list]]) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    path = tmp_path / "changes.xlsx"
    wb.save(path)
    return path


def test_reads_rows_and_skips_blanks(tmp_path):
    path = _write(
        tmp_path,
        {
            "Hosts": [
                ["action", "name", "value", "description"],
                ["create", "WEB01", "10.1.1.1", "web server"],
                [None, None, None, None],
                ["delete", "OLD01", "10.1.1.9", None],
            ]
        },
    )
    rows = parse_workbook(path, SPEC)
    assert len(rows["Hosts"]) == 2
    assert rows["Hosts"][0] == {
        "action": "create",
        "name": "WEB01",
        "value": "10.1.1.1",
        "description": "web server",
    }


def test_column_order_does_not_matter(tmp_path):
    path = _write(
        tmp_path,
        {"Hosts": [["name", "value", "action"], ["WEB01", "10.1.1.1", "create"]]},
    )
    rows = parse_workbook(path, SPEC)
    assert rows["Hosts"][0]["action"] == "create"
    assert rows["Hosts"][0]["name"] == "WEB01"


def test_readme_and_unknown_sheets_are_ignored(tmp_path):
    path = _write(
        tmp_path,
        {
            "README": [["Instructions"]],
            "Nonsense": [["a", "b"]],
            "Hosts": [["action", "name", "value"], ["create", "WEB01", "10.1.1.1"]],
        },
    )
    rows = parse_workbook(path, SPEC)
    assert set(rows) == {"Hosts"}


def test_numeric_cells_are_not_rendered_as_floats(tmp_path):
    spec = {"Ports": ["action", "name", "protocol", "port"]}
    path = _write(
        tmp_path,
        {"Ports": [["action", "name", "protocol", "port"], ["create", "HTTP-ALT", "TCP", 8080]]},
    )
    rows = parse_workbook(path, spec)
    assert rows["Ports"][0]["port"] == "8080"


def test_workbook_without_known_sheets_is_rejected(tmp_path):
    path = _write(tmp_path, {"Random": [["a"], ["b"]]})
    with pytest.raises(WorkbookError):
        parse_workbook(path, SPEC)


def test_corrupt_file_is_rejected(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(BytesIO(b"not a workbook").getvalue())
    with pytest.raises(WorkbookError):
        parse_workbook(path, SPEC)
