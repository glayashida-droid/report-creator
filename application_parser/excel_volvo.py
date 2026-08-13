"""沃尔沃/极星单页申请单解析（QP-VBD 专用格式）。"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from application_parser.models import ApplicationData, FileSource
from application_parser.excel_checkbox import yes_no_choice_on_excel_row
from application_parser.excel_parser import (
    _collect_sample_row_candidates,
    _effective_sample_storage_key,
    _has_chinese,
    _is_application_no_label,
    _is_instruction_text,
    _is_valid_field_label,
    _normalize_sample_key,
    _should_include_sample_row,
)
from application_parser.field_extract import is_blank_or_slash, is_quantity_sample_field, values_match
from application_parser.field_extract_applicant import split_bilingual_cell
from application_parser.field_extract_labels import clean_label, normalize_sample_field_key
from application_parser.report_language import english_sample_field_to_cn
from application_parser.encoding_io import load_workbook_from_bytes, normalize_upload_filename, safe_text

_VOLVO_SHEET_HINTS = ("沃尔沃", "volvo", "vcc", "polestar")
_SAMPLE_SECTION_MARKERS = ("测试样品信息", "test sample", "test sample name", "测试样品名称")
_REMARK_STOP_MARKERS = ("备注", "remark")
_REPORT_SAME_QUESTION = "company on report as same as applicant"
_SUPPLEMENT_COMPANY_LABEL = "如果选否，请补充"
_SKIP_PRE_SAMPLE_LABEL_MARKERS = (
    "company on report as same as",
    "company on invoice as same as",
    _SUPPLEMENT_COMPANY_LABEL,
    "一级供应商联系",
    "tire 1 supplier contact",
    "联系人",
    "contact person",
    "实验目的",
    "purpose of test",
    "是否复测",
    "retest or not",
    "整改方案",
    "root cause",
    "测试样品信息",
)
_VOLVO_OUTLINE_SKIP_KEYS = frozenset({"测试项目", "测试依据"})
_VOLVO_KEY_ALIASES = {
    "测试样品名称": "样品名称",
    "零件名称": "零件名称",
}


def _cell_str(value) -> str:
    return safe_text(value)


def _strip_bracket_label(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"^[【\[]+|[】\]]+$", "", s)
    return s.strip()


def _normalize_volvo_field_key(label: str) -> str:
    raw = _strip_bracket_label(label)
    raw = raw.split("\n")[0].strip()
    cn = clean_label(raw) or raw
    cn = _strip_bracket_label(cn)
    if cn in _VOLVO_KEY_ALIASES:
        return _VOLVO_KEY_ALIASES[cn]
    normalized = normalize_sample_field_key(cn) or cn
    if normalized in _VOLVO_KEY_ALIASES:
        return _VOLVO_KEY_ALIASES[normalized]
    return normalized


def _merged_top_left_map(sheet) -> Dict[Tuple[int, int], Tuple[int, int, object]]:
    mapping: Dict[Tuple[int, int], Tuple[int, int, object]] = {}
    for merged in sheet.merged_cells.ranges:
        value = sheet.cell(merged.min_row, merged.min_col).value
        for row in range(merged.min_row, merged.max_row + 1):
            for col in range(merged.min_col, merged.max_col + 1):
                mapping[(row, col)] = (merged.min_row, merged.min_col, value)
    return mapping


def _effective_value(sheet, row: int, col: int, merge_map) -> object:
    if (row, col) in merge_map:
        return merge_map[(row, col)][2]
    return sheet.cell(row, col).value


def _row_texts(sheet, row: int, merge_map, max_col: Optional[int] = None) -> List[str]:
    limit = max_col or sheet.max_column
    return [_cell_str(_effective_value(sheet, row, col, merge_map)) for col in range(1, limit + 1)]


def _find_volvo_sheet(wb):
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        title = (ws.title or "").lower().replace(" ", "")
        if any(h.lower().replace(" ", "") in title for h in _VOLVO_SHEET_HINTS):
            return ws
    visible = [ws for ws in wb.worksheets if ws.sheet_state == "visible"]
    return visible[0] if visible else wb.active


def _locate_sample_section_rows(sheet, merge_map) -> Tuple[int, int]:
    """返回 (首行样品字段行, 备注行) 均为 1-based；备注行仅作上界。"""
    start_row = 0
    remark_row = sheet.max_row + 1
    for row in range(1, sheet.max_row + 1):
        label = _row_label_text(sheet, row, merge_map)
        lower = label.lower()
        if not start_row and any(m in label or m in lower for m in _SAMPLE_SECTION_MARKERS):
            start_row = row + 1 if "测试样品信息" in label or "sample information" in lower else row
            continue
        if start_row and label:
            norm = _normalize_volvo_field_key(label)
            if norm in ("备注",) or "remark" in lower.split("\n")[0].lower():
                remark_row = row
                break
    if not start_row:
        for row in range(1, sheet.max_row + 1):
            label = _row_label_text(sheet, row, merge_map)
            if "test sample name" in label.lower() or "测试样品名称" in label:
                start_row = row
                break
    return start_row, remark_row


def _row_label_text(sheet, row: int, merge_map) -> str:
    for col in range(1, 5):
        text = _cell_str(_effective_value(sheet, row, col, merge_map)).strip()
        if text and not _is_instruction_text(text):
            return text
    return ""


def _value_candidates_from_row(sheet, row: int, merge_map, *, value_start_col: int = 5) -> List[str]:
    row_cells = [
        _effective_value(sheet, row, col, merge_map)
        for col in range(1, sheet.max_column + 1)
    ]
    padded = (None,) + tuple(row_cells[value_start_col - 1 :])
    return _collect_sample_row_candidates(padded)


def _parse_applicant_block(
    sheet, merge_map, *, stop_before_row: int
) -> Tuple[str, str, str, str]:
    name_cn = name_en = address_cn = address_en = ""
    for row in range(1, min(stop_before_row, sheet.max_row + 1)):
        label = ""
        value = ""
        texts = _row_texts(sheet, row, merge_map)
        for col_idx, text in enumerate(texts, start=1):
            if not text:
                continue
            lower = text.lower()
            if not label and (
                "applicant company" in lower
                or "申请公司" in text
                or ("applicant address" in lower or ("地址" in text and "applicant" in lower))
            ):
                label = text
                for val_col in range(col_idx + 1, len(texts) + 1):
                    val = texts[val_col - 1]
                    if val and not _is_instruction_text(val, label=label):
                        value = val
                        break
                break
        if not label:
            for col in range(1, 5):
                text = _cell_str(_effective_value(sheet, row, col, merge_map))
                if not text:
                    continue
                lower = text.lower()
                if "applicant company" in lower or "申请公司" in text:
                    label = text
                    for val_col in range(6, sheet.max_column + 1):
                        val = _cell_str(_effective_value(sheet, row, val_col, merge_map))
                        if val and not _is_instruction_text(val, label=label):
                            value = val
                            break
                    break
                if "applicant address" in lower or ("【" in text and "地址" in text and "applicant" in lower):
                    label = text
                    for val_col in range(6, sheet.max_column + 1):
                        val = _cell_str(_effective_value(sheet, row, val_col, merge_map))
                        if val and not _is_instruction_text(val, label=label):
                            value = val
                            break
                    break
        if not label or not value:
            continue
        lower = label.lower()
        val_cn, val_en = split_bilingual_cell(value)
        if "company" in lower or "申请公司" in label:
            name_cn = val_cn or value
            name_en = val_en or ""
        elif "address" in lower or "地址" in label:
            address_cn = val_cn or value
            address_en = val_en or ""
    return name_cn, name_en, address_cn, address_en


def _find_report_same_row(sheet, merge_map, *, stop_before_row: int) -> int:
    for row in range(1, min(stop_before_row, sheet.max_row + 1)):
        for col in range(1, 6):
            text = _cell_str(_effective_value(sheet, row, col, merge_map)).lower()
            if _REPORT_SAME_QUESTION in text:
                return row
    return 0


def _parse_supplement_row(sheet, row: int, merge_map) -> Tuple[str, str]:
    """选「否」时补充的公司名与地址。"""
    name_val = ""
    addr_val = ""
    name_label_col = 0
    addr_label_col = 0
    col_values: Dict[int, str] = {}
    for col in range(1, sheet.max_column + 1):
        text = _cell_str(_effective_value(sheet, row, col, merge_map)).strip()
        if text:
            col_values[col] = text
    for col, text in col_values.items():
        if _SUPPLEMENT_COMPANY_LABEL in text:
            name_label_col = col
        if text in ("地址", "Address") or text.strip() == "地址":
            addr_label_col = col
    if name_label_col:
        for col in sorted(col_values):
            if col <= name_label_col:
                continue
            if addr_label_col and col >= addr_label_col:
                break
            candidate = col_values[col]
            if _SUPPLEMENT_COMPANY_LABEL not in candidate and candidate not in ("地址", "Address"):
                name_val = candidate
                break
    if addr_label_col:
        for col in sorted(col_values):
            if col <= addr_label_col:
                continue
            candidate = col_values[col]
            if candidate not in ("地址", "Address"):
                addr_val = candidate
                break
    return name_val, addr_val


def _resolve_report_title_fields(
    file_bytes: bytes,
    sheet,
    merge_map,
    *,
    question_row: int,
    supplement_row: int,
) -> Tuple[str, str, str, str]:
    choice = yes_no_choice_on_excel_row(file_bytes, question_row) if question_row else None
    supplement_name, supplement_addr = (
        _parse_supplement_row(sheet, supplement_row, merge_map) if supplement_row else ("", "")
    )
    if choice is None:
        if supplement_name or supplement_addr:
            choice = False
        else:
            choice = True
    if choice:
        return "", "", "", ""
    name_cn, name_en = split_bilingual_cell(supplement_name)
    addr_cn, addr_en = split_bilingual_cell(supplement_addr)
    return (
        name_cn or supplement_name,
        name_en,
        addr_cn or supplement_addr,
        addr_en,
    )


def _is_volvo_instruction_candidate(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    if _is_instruction_text(s):
        return True
    if s.startswith("(") or s.startswith("（"):
        return True
    if s in ("地址", "Address"):
        return True
    return False


def _filter_value_candidates(candidates: List[str]) -> List[str]:
    return [c for c in candidates if not _is_volvo_instruction_candidate(c)]


def _should_skip_pre_sample_label(label: str) -> bool:
    lower = (label or "").lower()
    return any(m in label or m in lower for m in _SKIP_PRE_SAMPLE_LABEL_MARKERS)


def _parse_pre_sample_fields(
    sheet, merge_map, *, start_row: int, end_row: int
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    sample_info: Dict[str, str] = {}
    sample_info_candidates: Dict[str, List[str]] = {}

    def _store(storage_key: str, candidates: List[str]) -> None:
        active = _filter_value_candidates(candidates)
        if not storage_key or not active:
            return
        sample_info[storage_key] = active[0]
        sample_info_candidates[storage_key] = active

    for row in range(start_row, end_row):
        label_raw = _row_label_text(sheet, row, merge_map)
        if not label_raw or _should_skip_pre_sample_label(label_raw):
            continue
        storage_key = _normalize_volvo_field_key(label_raw)
        if not storage_key:
            continue
        candidates = _filter_value_candidates(_value_candidates_from_row(sheet, row, merge_map))
        if candidates:
            _store(storage_key, candidates)
    return sample_info, sample_info_candidates


def _merge_sample_dicts(
    primary: Dict[str, str],
    extra: Dict[str, str],
    primary_cands: Dict[str, List[str]],
    extra_cands: Dict[str, List[str]],
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    merged_info = dict(extra)
    merged_info.update(primary)
    merged_cands = dict(extra_cands)
    merged_cands.update(primary_cands)
    return merged_info, merged_cands


def _parse_sample_block(
    sheet, merge_map, *, start_row: int, end_row: int
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    sample_info: Dict[str, str] = {}
    sample_info_candidates: Dict[str, List[str]] = {}
    last_cn_key = ""

    def _store_sample_row(storage_key: str, candidates: List[str]) -> None:
        nonlocal last_cn_key
        if not storage_key or not candidates:
            last_cn_key = ""
            return
        if all(is_blank_or_slash(c) for c in candidates):
            last_cn_key = ""
            return
        keep_all = is_quantity_sample_field(storage_key)
        existing = sample_info_candidates.get(storage_key) or []
        merged: List[str] = list(existing)
        for val in candidates:
            if is_blank_or_slash(val):
                if merged and any(not is_blank_or_slash(item) for item in merged):
                    continue
                if not keep_all and any(values_match(val, item) for item in merged):
                    continue
                merged.append(val)
                continue
            if not keep_all and any(values_match(val, item) for item in merged):
                continue
            merged.append(val)
        sample_info[storage_key] = merged[0]
        sample_info_candidates[storage_key] = merged
        last_cn_key = storage_key

    for row in range(start_row, end_row):
        label_raw = _row_label_text(sheet, row, merge_map)
        if not label_raw:
            if last_cn_key:
                candidates = _value_candidates_from_row(sheet, row, merge_map)
                if candidates:
                    _store_sample_row(last_cn_key, candidates)
            continue
        key = _normalize_sample_key(label_raw)
        storage_key = _normalize_volvo_field_key(label_raw)
        if not storage_key or storage_key in _VOLVO_OUTLINE_SKIP_KEYS:
            last_cn_key = ""
            continue
        candidates = _filter_value_candidates(_value_candidates_from_row(sheet, row, merge_map))
        if (
            storage_key
            and last_cn_key
            and not _has_chinese(key)
            and _effective_sample_storage_key(key)
        ):
            en_key = english_sample_field_to_cn(key) or ""
            if en_key and sample_info.get(last_cn_key) is not None:
                storage_key = last_cn_key
        if _should_include_sample_row(key, candidates) or (
            storage_key and candidates and not all(is_blank_or_slash(c) for c in candidates)
        ):
            _store_sample_row(storage_key, candidates)
        else:
            last_cn_key = ""
    return sample_info, sample_info_candidates


def _parse_application_number(sheet, merge_map) -> str:
    for row in range(1, sheet.max_row + 1):
        for col in range(1, min(8, sheet.max_column)):
            label = _cell_str(_effective_value(sheet, row, col, merge_map))
            if not _is_application_no_label(label):
                continue
            for val_col in range(col + 1, sheet.max_column + 1):
                value = _cell_str(_effective_value(sheet, row, val_col, merge_map)).strip()
                if value and _is_valid_field_label(label):
                    return value
    return ""


def parse_volvo_application(file_bytes: bytes, filename: str) -> ApplicationData:
    wb = load_workbook_from_bytes(file_bytes, data_only=True)
    filename = normalize_upload_filename(filename) or "application.xlsx"
    sheet = _find_volvo_sheet(wb)
    merge_map = _merged_top_left_map(sheet)

    sample_start, remark_row = _locate_sample_section_rows(sheet, merge_map)
    header_stop = sample_start if sample_start > 0 else sheet.max_row
    pre_sample_end = sample_start if sample_start > 0 else header_stop

    name_cn, name_en, address_cn, address_en = _parse_applicant_block(
        sheet, merge_map, stop_before_row=pre_sample_end
    )
    question_row = _find_report_same_row(sheet, merge_map, stop_before_row=pre_sample_end)
    supplement_row = question_row + 1 if question_row else 0
    report_title_name_cn, report_title_name_en, report_title_address_cn, report_title_address_en = (
        _resolve_report_title_fields(
            file_bytes,
            sheet,
            merge_map,
            question_row=question_row,
            supplement_row=supplement_row,
        )
    )

    sample_info: Dict[str, str] = {}
    sample_info_candidates: Dict[str, List[str]] = {}
    # 本导出包故意不解析沃尔沃页内「测试项目 / 测试依据」行。
    if supplement_row and pre_sample_end > supplement_row + 1:
        pre_info, pre_cands = _parse_pre_sample_fields(
            sheet,
            merge_map,
            start_row=supplement_row + 1,
            end_row=pre_sample_end,
        )
        sample_info.update(pre_info)
        sample_info_candidates.update(pre_cands)
    if sample_start and remark_row > sample_start:
        block_info, block_cands = _parse_sample_block(
            sheet,
            merge_map,
            start_row=sample_start,
            end_row=remark_row,
        )
        sample_info, sample_info_candidates = _merge_sample_dicts(
            block_info, sample_info, block_cands, sample_info_candidates
        )

    application_no = _parse_application_number(sheet, merge_map)
    if application_no:
        sample_info = {"申请单号": application_no, **sample_info}
        sample_info_candidates = {"申请单号": [application_no], **sample_info_candidates}

    applicant_name = name_cn or name_en
    applicant_address = address_cn or address_en

    return ApplicationData(
        source=FileSource(file_type="application", filename=filename),
        applicant_name=applicant_name,
        applicant_address=applicant_address,
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
        report_title_name_cn=report_title_name_cn,
        report_title_name_en=report_title_name_en,
        report_title_address_cn=report_title_address_cn,
        report_title_address_en=report_title_address_en,
        sample_info=sample_info,
        sample_info_candidates=sample_info_candidates,
        sample_column_names=[],
    )
