"""送样/检测数量解析与比对。"""
from __future__ import annotations

import re
from typing import List, Optional

from application_parser.field_extract_labels import normalize_sample_field_key
from application_parser.report_language import english_sample_field_to_cn

# 试验/送样数量单位：pcs 与 pc（单数）等价；sets 仅见于英文首页表
QUANTITY_UNIT_SUFFIX_ALT = "pcs|pc|件|个|组"

_QUANTITY_UNIT_SUFFIX_RE = re.compile(
    rf"^\s*(\d+)\s*(?:{QUANTITY_UNIT_SUFFIX_ALT}|sets?)?\s*$",
    re.IGNORECASE,
)
_QUANTITY_SUM_SEP_RE = re.compile(r"[+＋]")


def try_parse_quantity_number(value: str) -> Optional[int]:
    """送样数量等：申请单常只写数字，报告常带 pcs/pc/件/个/组，比对时只比数字。"""
    raw = (value or "").strip()
    if not raw:
        return None
    m = _QUANTITY_UNIT_SUFFIX_RE.match(raw)
    if m:
        return int(m.group(1))
    return None


def parse_compound_sample_quantity(value: str) -> Optional[int]:
    """首页送样数「30pcs+10pcs」→ 40；单值仍走 try_parse_quantity_number。"""
    raw = (value or "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in _QUANTITY_SUM_SEP_RE.split(raw) if p.strip()]
    if len(parts) >= 2:
        nums: List[int] = []
        for part in parts:
            n = try_parse_quantity_number(part)
            if n is None:
                return None
            nums.append(n)
        return sum(nums)
    return try_parse_quantity_number(raw)


_QUANTITY_UNIT_TOKEN_RE = re.compile(
    rf"(?:{QUANTITY_UNIT_SUFFIX_ALT}|sets?)\b",
    re.IGNORECASE,
)
# 汇总表「样品」列偶发只写数量数字（1 / 10 / 80），无 pc。
# 不用前导零形式（001、01），那些更像短样品序号。
_SHORT_BARE_QUANTITY_RE = re.compile(r"^[1-9]\d{0,2}$")


def looks_like_sample_quantity_text(value: str) -> bool:
    """判断文案是否像送样/检测数量，不能当作样品编号规格。

    覆盖：
    - 带单位：``1pc`` / ``2 pcs`` / ``10PCS`` / ``30pcs+10pcs`` / ``24组``
    - 无单位短数字：``1`` / ``10`` / ``80``（完整样品号通常很长，且常含字母或 ``-``/``~``）
    - 无单位相加：``5+5`` / ``30+10``

    不含：``001`` / ``01~80`` / ``A2260…-A01`` 等编号或范围写法。
    """
    raw = (value or "").strip()
    if not raw:
        return False
    if _QUANTITY_UNIT_TOKEN_RE.search(raw):
        if parse_compound_sample_quantity(raw) is not None:
            return True
        return try_parse_quantity_number(raw) is not None
    if _SHORT_BARE_QUANTITY_RE.fullmatch(raw):
        return True
    parts = [p.strip() for p in _QUANTITY_SUM_SEP_RE.split(raw) if p.strip()]
    if len(parts) >= 2 and all(_SHORT_BARE_QUANTITY_RE.fullmatch(p) for p in parts):
        return True
    return False


def quantity_values_match(app_val: str, report_val: str) -> bool:
    left = try_parse_quantity_number(app_val)
    right = parse_compound_sample_quantity(report_val)
    if right is None:
        right = try_parse_quantity_number(report_val)
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


def is_quantity_sample_field(app_key: str) -> bool:
    key = normalize_sample_field_key(app_key)
    if key == "送样数量" or "送样数量" in key:
        return True
    return english_sample_field_to_cn(app_key) == "送样数量"


def quantity_candidates_total(candidates: List[str]) -> Optional[int]:
    """申请单 Sheet2 各组样品列数量之和（仅当各列均可解析为整数时）。"""
    nums: List[int] = []
    for candidate in candidates:
        n = try_parse_quantity_number(candidate)
        if n is None:
            return None
        nums.append(n)
    return sum(nums) if nums else None
