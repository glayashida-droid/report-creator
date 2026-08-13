"""申请单多样品列 vs 报告值的行级匹配。"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from application_parser.field_extract_labels import normalize_sample_field_key
from application_parser.field_extract_quantity import (
    is_quantity_sample_field,
    parse_compound_sample_quantity,
    quantity_candidates_total,
    try_parse_quantity_number,
)
from application_parser.report_language import ordered_application_candidates

# Late-bound imports from field_extract_match to avoid cycles at module load for values_match etc.
# We import what we need inside functions OR import from a thin values module.
# For now import from field_extract_values (created next).
from application_parser.field_extract_values import (
    is_blank_or_slash,
    normalize_compare_value,
    oem_values_match,
    try_parse_calendar_date,
    values_match,
)

_REPORT_MULTI_VALUE_SPLIT_RE = re.compile(r"[;；,，\n]+")

_LH_RH_PART_RE = re.compile(r"(LH|RH)\s*[：:]\s*(\S+)", re.IGNORECASE)


def _extract_lh_rh_parts(text: str) -> Dict[str, str]:
    parts: Dict[str, str] = {}
    for m in _LH_RH_PART_RE.finditer(text or ""):
        key = m.group(1).upper()
        val = re.sub(r"[\s\-_/]+", "", m.group(2)).upper()
        if val:
            parts[key] = val
    return parts


def _lh_rh_values_match(candidates: List[str], report_val: str) -> bool:
    app_text = "\n".join(c for c in candidates if not is_blank_or_slash(c))
    app_parts = _extract_lh_rh_parts(app_text)
    rep_parts = _extract_lh_rh_parts(report_val)
    if not app_parts or not rep_parts:
        return False
    return all(rep_parts.get(side) == val for side, val in app_parts.items())


def _split_multivalue_candidate(text: str) -> List[str]:
    parts = re.split(r"[\n,，;；]+", text or "")
    return [p.strip() for p in parts if p.strip() and not is_blank_or_slash(p.strip())]


def _significant_tokens(value: str) -> set[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z]+|\d+", value or "")
    return {
        (t.upper() if t.isascii() else t)
        for t in tokens
        if t.isdigit() or len(t) >= 2
    }


def _compare_units_from_candidates(candidates: List[str]) -> List[str]:
    units: List[str] = []
    for candidate in candidates:
        if is_blank_or_slash(candidate):
            continue
        parts = _split_multivalue_candidate(candidate)
        if len(parts) >= 2:
            units.extend(parts)
        else:
            units.append(candidate)
    return units


def _compare_unit_covered(unit: str, report_val: str) -> bool:
    if values_match(unit, report_val):
        return True
    if _candidate_covered_in_report(unit, report_val):
        return True
    unit_tokens = _significant_tokens(unit)
    return bool(unit_tokens and unit_tokens <= _significant_tokens(report_val))


def _candidate_covered_in_report(candidate: str, report_val: str) -> bool:
    nc = normalize_compare_value(candidate)
    nr = normalize_compare_value(report_val)
    if not nc:
        return True
    if nc in nr:
        return True
    base = nc
    suffix = ""
    for marker in ("左舵", "右舵"):
        if marker in nc:
            suffix = marker
            base = nc.replace(marker, "")
            break
    if not suffix:
        return False
    if base and base not in nr:
        return False
    return suffix in nr


def _matched_candidate_label(candidates: List[str]) -> str:
    active = [c for c in candidates if not is_blank_or_slash(c)]
    if not active:
        return ""
    if len(active) == 1:
        return active[0]
    return " / ".join(active)


def report_sample_value_has_merged_extra(
    report_val: str,
    matched_candidate: str,
    *,
    english_report: bool = False,
) -> bool:
    """报告值仅部分 token 命中申请单，且仍含日期等其它字段的实质片段（分行误合并）。"""
    display = _sample_field_compare_display(report_val, english_report=english_report)
    if not display or not matched_candidate:
        return False
    if values_match(matched_candidate, display):
        return False
    tokens = [
        token.strip()
        for token in report_compare_tokens(display)
        if token.strip() and not re.fullmatch(r"[:：\s]+", token.strip())
    ]
    if len(tokens) <= 1:
        return False
    if not any(values_match(matched_candidate, token) for token in tokens):
        return False
    extras = [token for token in tokens if not values_match(matched_candidate, token)]
    if not extras:
        return False
    from application_parser._stubs import extract_value_portion

    return any(
        try_parse_calendar_date(extract_value_portion(token) or token) for token in extras
    )


def report_compare_tokens(value: str) -> List[str]:
    display = (value or "").strip()
    if not display:
        return [""]
    parts = [p.strip() for p in _REPORT_MULTI_VALUE_SPLIT_RE.split(display) if p.strip()]
    return parts or [display]


def _sample_field_compare_display(report_val: str, *, english_report: bool = False) -> str:
    """报告样品信息中英连写（如「黑色Black」）时拆中文段比对。

    仅用 `_split_inline_bilingual`（同委托方连写切分）；含 `/` 的复杂写法保持原值。
    """
    from application_parser.field_extract_applicant import _split_inline_bilingual

    display = (report_val if report_val is not None else "").strip()
    if not display:
        return display
    inline = _split_inline_bilingual(display)
    if not inline:
        return display
    cn, en = inline
    if "/" in cn:
        return display
    return en if english_report else cn


def match_application_row_value(
    candidates: List[str],
    report_val: str,
    *,
    field_key: str = "",
    english_report: bool = False,
) -> Optional[str]:
    display = _sample_field_compare_display(report_val, english_report=english_report)
    ordered = ordered_application_candidates(
        candidates, display, english_report=english_report
    )
    if is_blank_or_slash(display):
        for candidate in ordered:
            if is_blank_or_slash(candidate):
                return candidate
        return None
    for candidate in ordered:
        if values_match(candidate, display):
            return candidate
    if normalize_sample_field_key(field_key) == "主机厂" and oem_values_match(
        ordered[0] if ordered else "", display
    ):
        return _matched_candidate_label(ordered)
    if _lh_rh_values_match(ordered, display):
        return _matched_candidate_label(ordered)
    for token in report_compare_tokens(display):
        for candidate in ordered:
            if values_match(candidate, token):
                return candidate
    if is_quantity_sample_field(field_key):
        report_qty = parse_compound_sample_quantity(display)
        if report_qty is None:
            report_qty = try_parse_quantity_number(display)
        if report_qty is None:
            for token in report_compare_tokens(display):
                report_qty = parse_compound_sample_quantity(token)
                if report_qty is None:
                    report_qty = try_parse_quantity_number(token)
                if report_qty is not None:
                    break
        total = quantity_candidates_total(ordered)
        if report_qty is not None and total is not None and total == report_qty:
            return str(total)
    if _all_candidates_contained_in_report(ordered, display):
        return _matched_candidate_label(ordered)
    return None


def _all_candidates_contained_in_report(candidates: List[str], report_val: str) -> bool:
    """申请单多列/多行样品：拆分后在报告合并写法中均可找到（如 左舵/右舵 连写）。"""
    units = _compare_units_from_candidates(candidates)
    if len(units) < 2:
        return False
    return all(_compare_unit_covered(u, report_val) for u in units)
