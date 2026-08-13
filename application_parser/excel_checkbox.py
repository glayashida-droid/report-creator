"""从 xlsx VML 绘图层读取 Excel 表单勾选框（是/否）状态。"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import List, Optional
from xml.etree import ElementTree as ET

_ANCHOR_RE = re.compile(
    r"<x:Anchor>(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)</x:Anchor>"
)
_CHECKED_RE = re.compile(r"<x:Checked>(\d)</x:Checked>")
_TEXTBOX_RE = re.compile(
    r"<v:textbox[^>]*>.*?<p>(.*?)</p>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ExcelCheckbox:
    """单个勾选框：锚定行（0-based 顶行）与可见文案。"""

    row_top: int
    label: str
    checked: bool


def _strip_xml_text(raw: str) -> str:
    text = _TAG_RE.sub("", raw or "")
    return re.sub(r"\s+", " ", text).strip()


def _is_yes_label(label: str) -> bool:
    t = (label or "").strip().lower()
    if not t:
        return False
    if t.startswith("是") or t.startswith("yes"):
        return True
    return "是 yes" in t or t == "yes"


def _is_no_label(label: str) -> bool:
    t = (label or "").strip().lower()
    if not t:
        return False
    if t.startswith("否") or t.startswith("no"):
        return True
    return "否 no" in t or t == "no"


def read_excel_checkboxes(file_bytes: bytes) -> List[ExcelCheckbox]:
    """解析 xlsx 内全部 VML 勾选框。"""
    boxes: List[ExcelCheckbox] = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            vml_names = [n for n in zf.namelist() if n.startswith("xl/drawings/vmlDrawing") and n.endswith(".vml")]
            for name in vml_names:
                xml_text = zf.read(name).decode("utf-8", errors="ignore")
                boxes.extend(_parse_vml_checkboxes(xml_text))
    except (zipfile.BadZipFile, KeyError, OSError):
        return []
    return boxes


def _parse_vml_checkboxes(xml_text: str) -> List[ExcelCheckbox]:
    out: List[ExcelCheckbox] = []
    for block in re.split(r"<v:shape\b", xml_text):
        if "ObjectType=\"Checkbox\"" not in block and "ObjectType='Checkbox'" not in block:
            continue
        anchor_m = _ANCHOR_RE.search(block)
        if not anchor_m:
            continue
        row_top = int(anchor_m.group(3))
        checked = bool(_CHECKED_RE.search(block))
        label = ""
        text_m = _TEXTBOX_RE.search(block)
        if text_m:
            label = _strip_xml_text(text_m.group(1))
        out.append(ExcelCheckbox(row_top=row_top, label=label, checked=checked))
    return out


def yes_no_choice_on_excel_row(file_bytes: bytes, excel_row: int) -> Optional[bool]:
    """读取某 Excel 行（1-based）附近「是/否」勾选结果。

    返回 True=选是，False=选否，None=无法判定（由调用方走兜底逻辑）。
    """
    target = excel_row - 1
    nearby = [
        b
        for b in read_excel_checkboxes(file_bytes)
        if abs(b.row_top - target) <= 1
    ]
    yes_checked = any(b.checked and _is_yes_label(b.label) for b in nearby)
    no_checked = any(b.checked and _is_no_label(b.label) for b in nearby)
    if yes_checked and not no_checked:
        return True
    if no_checked and not yes_checked:
        return False
    return None
