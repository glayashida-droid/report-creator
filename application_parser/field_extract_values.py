"""字段值模糊匹配、空值/日期等价、叙述型结果表判定。"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from application_parser.field_extract_quantity import (
    parse_compound_sample_quantity,
    quantity_values_match,
    try_parse_quantity_number,
)
from application_parser.sample_id_labels import is_result_sample_column_key

_PLACEHOLDER_APP_NUMBER_RE = re.compile(
    r"内部填写|此处\s*CTI|CTI\s*内部",
    re.IGNORECASE,
)
_GENERIC_MATERIAL_VALUES = frozenset(
    {"ASSY", "FINISHED", "总成", "NA", "N/A", "NONE", "无"}
)

_EMPTY_VALUE_SENTINELS = frozenset(
    {
        "/",
        "／",
        "-",
        "－",  # 全角连字符
        "—",
        "–",
        "无",
    }
)

def is_placeholder_application_number(value: str) -> bool:
    raw = (value or "").strip()
    if not raw or is_blank_or_slash(raw):
        return True
    return bool(_PLACEHOLDER_APP_NUMBER_RE.search(raw))


def is_generic_material_value(value: str) -> bool:
    compact = re.sub(r"[\s\-_/]+", "", (value or "")).upper()
    if not compact:
        return True
    if compact in _GENERIC_MATERIAL_VALUES:
        return True
    return compact in {"FINISHEDPRODUCTS", "FINISHEDPRODUCT"}


def oem_values_match(app_val: str, report_val: str) -> bool:
    """主机厂常见中英/简称互通（如 吉利GEELY ↔ Geely Automobile）。"""
    if values_match(app_val, report_val):
        return True
    a = (app_val or "").upper()
    b = (report_val or "").upper()
    pairs = (
        ("GEELY", ("吉利", "GEELY")),
        ("TESLA", ("特斯拉", "TESLA")),
        ("BYD", ("比亚迪", "BYD")),
    )
    for token, markers in pairs:
        if any(m.upper() in a or m in (app_val or "") for m in markers):
            return any(m.upper() in b or m in (report_val or "") for m in markers)
    return False


def is_narrative_results_table(rows: List[dict]) -> bool:
    """结果表仅有「检测结果」叙述列、无样品编号列。"""
    if not rows:
        return False
    from application_parser._stubs import is_result_description_column

    for row in rows:
        if not row:
            continue
        has_desc = any(is_result_description_column(str(k)) for k in row)
        has_sample = any(is_result_sample_column_key(str(k)) for k in row)
        if has_sample:
            return False
        if not has_desc:
            return False
    return True


def count_narrative_result_rows(rows: List[dict]) -> int:
    """叙述型结果表：中英重复行合并计数。"""
    from application_parser._stubs import is_result_description_column

    if not rows:
        return 0
    cn_rows: List[str] = []
    en_rows: List[str] = []
    for row in rows:
        for key, value in row.items():
            if not is_result_description_column(str(key)):
                continue
            text = str(value or "").strip()
            if not text:
                continue
            if re.search(r"[\u4e00-\u9fff]", text):
                cn_rows.append(text)
            else:
                en_rows.append(text)
    if cn_rows:
        return len(cn_rows)
    return len(en_rows) or len(rows)


def is_blank_or_slash(value: str | None) -> bool:
    """申请单/报告中「/」「-」「无」、空白、未填、NA 视为等价空值（首页样品信息比对用）。"""
    if value is None:
        return True
    stripped = (value or "").strip()
    if not stripped:
        return True
    if stripped in _EMPTY_VALUE_SENTINELS:
        return True
    upper = stripped.upper()
    if upper in ("NA", "N/A"):
        return True
    if stripped.startswith("不适用"):
        return True
    return False


def format_sample_field_display(value: str | None) -> str:
    """结果列表展示：保留 /、-、无 原文；仅完全无内容时标（空）。"""
    stripped = (value or "").strip()
    if not stripped:
        return "（空）"
    return stripped


def try_parse_calendar_date(value: str) -> Optional[Tuple[int, int, int]]:
    """Parse YYYY-M-D with optional trailing time (Excel datetime strings)."""
    raw = (value or "").strip()
    if not raw:
        return None
    date_part = raw.split()[0] if " " in raw else raw
    if "~" in date_part:
        date_part = date_part.split("~", 1)[0].strip()
    normalized = date_part.replace("/", "-").replace(".", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", normalized)
    if not m:
        return None
    year, month, day = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if month < 1 or month > 12 or day < 1 or day > 31:
        return None
    return year, month, day


def calendar_dates_equal(app_val: str, report_val: str) -> bool:
    left = try_parse_calendar_date(app_val)
    right = try_parse_calendar_date(report_val)
    return left is not None and right is not None and left == right


def normalize_compare_value(value: str) -> str:
    """比对用归一化：仅保留中文、字母、数字，忽略 /、（）等标点与空白。"""
    value = (value or "").strip()
    if not value:
        return ""
    chars: List[str] = []
    for ch in value:
        if "\u4e00" <= ch <= "\u9fff":
            chars.append(ch)
        elif ch.isascii() and ch.isalnum():
            chars.append(ch.upper())
    return "".join(chars)


def values_match(app_val: str, report_val: str) -> bool:
    if is_blank_or_slash(app_val) and is_blank_or_slash(report_val):
        return True
    if not app_val and not report_val:
        return True
    if app_val == report_val:
        return True
    if calendar_dates_equal(app_val, report_val):
        return True
    if quantity_values_match(app_val, report_val):
        return True
    a = normalize_compare_value(app_val)
    b = normalize_compare_value(report_val)
    if a and b and a == b:
        return True
    a_compact = re.sub(r"[\s\-_/]+", "", (app_val or "")).upper()
    b_compact = re.sub(r"[\s\-_/]+", "", (report_val or "")).upper()
    if a_compact and b_compact and a_compact == b_compact:
        return True
    # 编号/零件号等字母数字混合标识：不做“短串包含长串”的宽松匹配，避免字母偏差漏报。
    if (
        a_compact and b_compact
        and re.search(r"[A-Z]", a_compact) and re.search(r"\d", a_compact)
        and re.search(r"[A-Z]", b_compact) and re.search(r"\d", b_compact)
        and len(a_compact) >= 6 and len(b_compact) >= 6
    ):
        return False
    if a_compact and b_compact:
        shorter, longer = (
            (a_compact, b_compact) if len(a_compact) <= len(b_compact) else (b_compact, a_compact)
        )
        if shorter in longer and len(shorter) >= len(longer) * 0.85:
            return True
    return False


def match_application_number(app_no: str, report_no: str) -> bool:
    app_no = re.sub(r"\s", "", (app_no or ""))
    report_no = re.sub(r"\s", "", (report_no or ""))
    if not app_no or not report_no:
        return False
    return app_no in report_no or report_no.startswith(app_no)
