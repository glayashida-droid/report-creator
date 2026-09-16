"""Low-level python-docx helpers for the Geely ELP template (black vs blue runs)."""

from __future__ import annotations

from copy import deepcopy
from typing import Iterable, List, Optional, Sequence

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.table import Table
from docx.text.paragraph import Paragraph

BLUE_VALS = {"0000FF", "0070C0", "00B0F0"}
NSMAP_R = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
NSMAP_A = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def unique_cells(row) -> list:
    seen = set()
    out = []
    for cell in row.cells:
        cid = id(cell._tc)
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cell)
    return out


def cell_text(cell) -> str:
    return "".join((p.text or "") for p in cell.paragraphs).strip()


def run_color_val(run) -> str:
    rPr = run._r.find(qn("w:rPr"))
    if rPr is None:
        return ""
    color = rPr.find(qn("w:color"))
    if color is None:
        return ""
    return (color.get(qn("w:val")) or "").upper()


def run_is_blue(run) -> bool:
    return run_color_val(run) in BLUE_VALS


def cell_has_blue(cell) -> bool:
    for p in cell.paragraphs:
        for run in p.runs:
            if run_is_blue(run) and (run.text or "").strip():
                return True
    return False


def set_run_color(run, val: str) -> None:
    rPr = run._r.get_or_add_rPr()
    color = rPr.find(qn("w:color"))
    if color is None:
        color = OxmlElement("w:color")
        rPr.append(color)
    color.set(qn("w:val"), val)


def write_runs(paragraph, pieces: Sequence[tuple[str, Optional[str]]]) -> None:
    for run in list(paragraph.runs):
        run._element.getparent().remove(run._element)
    for text, color in pieces:
        run = paragraph.add_run(text)
        if color:
            set_run_color(run, color)


def set_blue_portion(cell, text: str) -> bool:
    """Replace blue runs. If the cell is all black, leave it. Empty cells get blue text."""
    blue_runs = []
    black_text = False
    for p in cell.paragraphs:
        for run in p.runs:
            if run_is_blue(run):
                blue_runs.append(run)
            elif (run.text or "").strip():
                black_text = True
    value = "" if text is None else str(text)
    if blue_runs:
        blue_runs[0].text = value
        for run in blue_runs[1:]:
            run.text = ""
        return True
    if black_text:
        return False
    paragraph = cell.paragraphs[0] if cell.paragraphs else None
    if paragraph is None:
        return False
    write_runs(paragraph, [(value, "0000FF")] if value else [("", "0000FF")])
    for extra in list(cell.paragraphs)[1:]:
        extra.text = ""
    return True


def force_blue_text(cell, text: str) -> None:
    """Write blue text even if the cell was black (used for allowed exceptions)."""
    value = "" if text is None else str(text)
    paragraph = cell.paragraphs[0] if cell.paragraphs else None
    if paragraph is None:
        return
    write_runs(paragraph, [(value, "0000FF")])
    for extra in list(cell.paragraphs)[1:]:
        extra.text = ""


def force_black_text(cell, text: str) -> None:
    value = "" if text is None else str(text)
    paragraph = cell.paragraphs[0] if cell.paragraphs else None
    if paragraph is None:
        return
    write_runs(paragraph, [(value, None)])
    for extra in list(cell.paragraphs)[1:]:
        extra.text = ""


def set_photo_caption(cell, index: int, description: str) -> None:
    label = f"图片{index}："
    desc = (description or "").strip() or "/"
    paragraph = cell.paragraphs[0] if cell.paragraphs else None
    if paragraph is None:
        return
    write_runs(paragraph, [(label, None), (desc, "0000FF")])
    for extra in list(cell.paragraphs)[1:]:
        extra.text = ""


def delete_table_row(table: Table, index: int) -> None:
    table._tbl.remove(table.rows[index]._tr)


def clone_table_row(table: Table, source_index: int) -> None:
    src = table.rows[source_index]._tr
    table._tbl.append(deepcopy(src))


def remove_drawings(cell) -> None:
    for drawing in list(cell._tc.iter(qn("w:drawing"))):
        parent = drawing.getparent()
        if parent is not None:
            parent.remove(drawing)
    for pict in list(cell._tc.iter(qn("w:pict"))):
        parent = pict.getparent()
        if parent is not None:
            parent.remove(pict)


def paragraph_style_name(paragraph: Paragraph) -> str:
    try:
        style = paragraph.style
        return (style.name if style is not None else "") or ""
    except Exception:
        return ""


def iter_body_children(doc) -> List:
    return [child for child in doc.element.body if child.tag != qn("w:sectPr")]


def wrap_paragraph(element, doc) -> Paragraph:
    return Paragraph(element, doc)


def wrap_table(element, doc) -> Table:
    return Table(element, doc)
