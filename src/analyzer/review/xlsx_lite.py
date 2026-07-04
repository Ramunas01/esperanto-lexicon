"""Minimal, dependency-free XLSX read/write for the gap-fill review harness.

``openpyxl`` is not installable in this environment (PEP 668), and the harness
must never touch the reviewer's live ``.xlsx`` (Excel holds it open). An XLSX is
just a zip of XML, so we read it with the standard library and write a *fresh*
viewable copy with all-inline strings — never patching the original in place.

Scope is deliberately tiny: one flat sheet of text/number cells, no styling,
no formulas. That is all the review workflow needs (snapshot in, viewable copy
out).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NSR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_letters(cell_ref: str) -> str:
    """Return the column-letter part of a cell reference (``B12`` -> ``B``)."""
    m = re.match(r"[A-Z]+", cell_ref)
    return m.group() if m else ""


def _col_index(letters: str) -> int:
    """Convert column letters to a 0-based index (``A`` -> 0, ``AA`` -> 26)."""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _index_to_col(idx: int) -> str:
    """Convert a 0-based column index to letters (0 -> ``A``, 26 -> ``AA``)."""
    idx += 1
    out = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _sheet_path(zf: zipfile.ZipFile, sheet_name: str | None) -> str:
    """Resolve a sheet name to its archive path (first sheet if name is None)."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    relmap = {r.get("Id"): r.get("Target") for r in rels}
    sheets = wb.find(f"{_NS}sheets")
    for s in sheets:
        if sheet_name is None or s.get("name") == sheet_name:
            target = relmap[s.get(f"{_NSR}id")].lstrip("/")
            return target if target.startswith("xl/") else "xl/" + target
    raise KeyError(f"sheet {sheet_name!r} not found in workbook")


def read_sheet(
    path: str | Path, sheet_name: str | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Read one worksheet into ``(header, rows)``.

    ``header`` is the first row's cell values in column order; each entry in
    ``rows`` is a dict keyed by header name (blank cells fill missing columns).
    Shared strings and inline strings are both resolved; numbers come through as
    their text.
    """
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sroot.findall(f"{_NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))

        def cell_value(c: ET.Element) -> str:
            t = c.get("t")
            if t == "inlineStr":
                node = c.find(f"{_NS}is")
                return "".join(x.text or "" for x in node.iter(f"{_NS}t")) if node is not None else ""
            v = c.find(f"{_NS}v")
            if v is None:
                return ""
            return shared[int(v.text)] if t == "s" else (v.text or "")

        root = ET.fromstring(zf.read(_sheet_path(zf, sheet_name)))
        raw_rows = root.find(f"{_NS}sheetData").findall(f"{_NS}row")

    def row_cells(row: ET.Element) -> dict[int, str]:
        return {
            _col_index(_col_letters(c.get("r", ""))): cell_value(c)
            for c in row
            if c.get("r")
        }

    if not raw_rows:
        return [], []
    header_cells = row_cells(raw_rows[0])
    width = (max(header_cells) + 1) if header_cells else 0
    header = [header_cells.get(i, "") for i in range(width)]

    rows: list[dict[str, str]] = []
    for row in raw_rows[1:]:
        cells = row_cells(row)
        rows.append({header[i]: cells.get(i, "") for i in range(width)})
    return header, rows


def write_xlsx(path: str | Path, header: list[str], rows: list[list[object]]) -> None:
    """Write a fresh single-sheet ``.xlsx`` with all cells as inline strings.

    No styling, no shared-string table — a clean, viewable copy. Numeric-looking
    values are still written as text, which Excel displays fine for review.
    """
    path = Path(path)

    def cell(ci: int, ri: int, value: object) -> str:
        ref = f"{_index_to_col(ci)}{ri}"
        text = _xml_escape("" if value is None else str(value))
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

    xml_rows = []
    all_rows = [header] + [list(r) for r in rows]
    for ri, r in enumerate(all_rows, start=1):
        cells = "".join(cell(ci, ri, v) for ci, v in enumerate(r))
        xml_rows.append(f'<row r="{ri}">{cells}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="reviewed" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
