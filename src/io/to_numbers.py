"""Extract Autoliv TO numbers from application sheet 3 「特殊要求」."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import List, Optional, Sequence, Tuple

from application_parser.encoding_io import load_workbook_from_bytes, safe_text
from application_parser.excel_sheet_locate import find_application_test_sheet

_TO_RE = re.compile(r"(?i)(?<![A-Za-z0-9])TO-(\d+)(?:-(\d{2}))?(?!\d)")
_AUTOLIV_MARK = "奥托立夫"


def is_autoliv_applicant(name: str) -> bool:
    return _AUTOLIV_MARK in (name or "")


def extract_to_numbers_from_text(text: str) -> List[str]:
    seen = set()
    out: List[str] = []
    for match in _TO_RE.finditer(text or ""):
        full = _canonical(match.group(1), match.group(2))
        if full not in seen:
            seen.add(full)
            out.append(full)
    return out


def format_to_numbers_display(tos: Sequence[str]) -> str:
    groups: OrderedDict[str, List[Optional[str]]] = OrderedDict()
    for raw in tos:
        parsed = _split_to(raw)
        if parsed is None:
            continue
        stem, suffix = parsed
        bucket = groups.setdefault(stem, [])
        if suffix not in bucket:
            bucket.append(suffix)
    parts: List[str] = []
    for stem, suffixes in groups.items():
        nonempty = [s for s in suffixes if s]
        has_bare = any(not s for s in suffixes)
        if nonempty and not has_bare:
            first, *rest = nonempty
            chunk = f"TO-{stem}-{first}"
            if rest:
                chunk += "/" + "/".join(rest)
            parts.append(chunk)
        elif nonempty and has_bare:
            parts.append(f"TO-{stem}/" + "/".join(nonempty))
        else:
            parts.append(f"TO-{stem}")
    return "，".join(parts)


def extract_to_numbers_from_application(file_bytes: bytes) -> List[str]:
    if not file_bytes:
        return []
    try:
        wb = load_workbook_from_bytes(file_bytes)
    except Exception:
        return []
    try:
        sheet = find_application_test_sheet(wb)
        if sheet is None:
            return []
        header_row, col = _find_special_req_header(sheet)
        if col is None:
            return []
        seen = set()
        out: List[str] = []
        start = (header_row or 1) + 1
        for row in sheet.iter_rows(min_row=start, min_col=col, max_col=col):
            cell = row[0]
            for item in extract_to_numbers_from_text(safe_text(cell.value)):
                if item not in seen:
                    seen.add(item)
                    out.append(item)
        return out
    finally:
        wb.close()


def apply_autoliv_to_numbers(state, file_bytes: bytes) -> None:
    name = (
        getattr(state, "applicant_name", "")
        or (getattr(state, "application_fields", None) or {}).get("申请公司")
        or ""
    )
    if not is_autoliv_applicant(str(name)):
        state.to_numbers = []
        state.to_numbers_display = ""
        return
    tos = extract_to_numbers_from_application(file_bytes)
    state.to_numbers = tos
    state.to_numbers_display = format_to_numbers_display(tos)


def _canonical(stem: str, suffix: Optional[str]) -> str:
    if suffix:
        return f"TO-{stem}-{suffix}"
    return f"TO-{stem}"


def _split_to(raw: str) -> Optional[Tuple[str, Optional[str]]]:
    match = _TO_RE.search(raw or "")
    if not match:
        return None
    return match.group(1), match.group(2)


def _header_key(value) -> str:
    return re.sub(r"\s+", "", safe_text(value))


def _find_special_req_header(sheet) -> Tuple[Optional[int], Optional[int]]:
    max_row = min(sheet.max_row or 1, 15)
    for row in sheet.iter_rows(min_row=1, max_row=max_row):
        for cell in row:
            if "特殊要求" in _header_key(cell.value):
                return cell.row, cell.column
    return None, sheet.max_column if sheet.max_column else None
