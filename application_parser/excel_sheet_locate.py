"""申请单 Excel 工作表按标签页名称定位（跳过隐藏的数据源页）。"""

from __future__ import annotations

import re
from typing import Optional

from application_parser.encoding_io import safe_text


def _normalize_sheet_title(name: str) -> str:
    return re.sub(r"\s+", "", safe_text(name))


def _sheet_name_matches(name: str, *substrings: str) -> bool:
    norm = _normalize_sheet_title(name)
    return any(sub in norm for sub in substrings)


def _visible_worksheets(wb) -> list:
    return [ws for ws in wb.worksheets if ws.sheet_state == "visible"]


def _find_sheet_by_title(wb, *substrings: str, fallback_index: Optional[int] = None):
    """按标签页名称定位工作表；未命中时回退到第 N 个可见表。"""
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        if _sheet_name_matches(ws.title, *substrings):
            return ws
    if fallback_index is None:
        return None
    visible = _visible_worksheets(wb)
    if 0 <= fallback_index < len(visible):
        return visible[fallback_index]
    return None


def find_application_selection_sheet(wb):
    return _find_sheet_by_title(wb, "应选信息", fallback_index=0)


def find_application_sample_sheet(wb):
    return _find_sheet_by_title(wb, "样品信息", fallback_index=1)


def find_application_test_sheet(wb):
    return _find_sheet_by_title(wb, "测试信息", "试验信息", fallback_index=2)
