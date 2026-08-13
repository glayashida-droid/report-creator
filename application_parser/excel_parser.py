import re
from typing import Dict, List, Optional, Tuple

from application_parser.models import ApplicationData, FileSource
from application_parser.field_extract import (
    applicant_pair_language,
    classify_applicant_pair,
    classify_payer_pair,
    is_blank_or_slash,
    is_same_as_applicant_value,
    is_quantity_sample_field,
    resolve_same_as_applicant,
    resolve_same_as_payer,
    resolve_report_title_reference,
    values_match,
)
from application_parser.field_extract_match import (
    _all_candidates_contained_in_report,
    sample_storage_keys_alias_equivalent,
)
from application_parser.field_extract_labels import extract_chinese_text, normalize_sample_field_key
from application_parser.excel_sheet_locate import (
    find_application_sample_sheet,
    find_application_selection_sheet,
)
from application_parser.report_language import english_sample_field_to_cn
from application_parser.encoding_io import load_workbook_from_bytes, normalize_upload_filename, safe_text

# Sheet2: never compare these fields (per business rules)
_SAMPLE_SKIP_KEYS = ("样品序号", "申请单样品需要")

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


def _cell_str(value) -> str:
    return safe_text(value)


def _normalize_label(text: str) -> str:
    text = _cell_str(text).lstrip("★* ").strip()
    return text


def _normalize_sample_key(key: str) -> str:
    key = _cell_str(key).strip("：:→* 　")
    return key


def _has_chinese(text: str) -> bool:
    return bool(_CHINESE_RE.search(text or ""))


def _is_instruction_text(text: str, *, label: str = "") -> bool:
    """过滤说明性长文；地址类字段允许更长（与 field_extract_applicant 一致）。"""
    label_norm = _normalize_label(label)
    lower = label_norm.lower()
    if "地址" in label_norm or ("address" in lower and "name" not in lower):
        return len(text or "") > 500
    if len(text) > 80:
        return True
    if re.match(r"^\d+[、.．]", text):
        return True
    markers = ("必填", "邮寄", "退回处理", "包装外部", "表中的", "均需要")
    return sum(1 for m in markers if m in text) >= 2


def _classify_report_title_pair(label: str, value: str) -> Optional[str]:
    """识别申请单中的“报告抬头公司/地址（Company shown on report）”字段。"""
    label_norm = _normalize_label(label)
    lower = label_norm.lower()
    value = _cell_str(value).strip()
    if not label_norm or not value or _is_instruction_text(value, label=label):
        return None
    # 常见标签：报告抬头公司 / Company shown on report / shown on report (address)
    if "抬头" not in label_norm and "shown on report" not in lower and "company shown" not in lower:
        return None
    if "地址" in label_norm or "address" in lower:
        return "address"
    if any(k in label_norm for k in ("公司", "单位", "委托方")) or any(
        k in lower for k in ("company", "customer", "applicant")
    ):
        return "name"
    return None


def _is_valid_field_label(label: str) -> bool:
    if not label or _is_instruction_text(label):
        return False
    if len(label) > 40:
        return False
    return True


def _extract_label_value_pairs(row_values: tuple) -> List[Tuple[str, str]]:
    cells = [_cell_str(v) for v in row_values]
    while cells and not cells[-1]:
        cells.pop()
    if not cells:
        return []

    pairs: List[Tuple[str, str]] = []
    if len(cells) >= 4:
        for label_idx, value_idx in ((0, 1), (2, 3)):
            if label_idx < len(cells) and value_idx < len(cells):
                label = cells[label_idx]
                value = cells[value_idx]
                if label and value and not _is_instruction_text(value, label=label):
                    pairs.append((label, value))
        if pairs:
            return pairs

    if len(cells) >= 2:
        label = cells[0]
        value = cells[1]
        if label and value and not _is_instruction_text(value, label=label):
            pairs.append((label, value))
    return pairs


def parse_application_sheet1(sheet) -> Tuple[str, str, str, str, str, str, str, str, str]:
    """
    申请单 Sheet1 典型布局：
    R3 左半:  | 申请单号(for CTI only) | A22504252521 |
    R6:       | ★申请公司            | 公司名（中文）| ★申请公司地址 | 地址（中文）|
    R7:       | ★Applicant Name      | EN 名         | ★Applicant Address | EN 址 |

    返回 (
      name_cn, name_en, address_cn, address_en, application_no,
      report_title_name_cn, report_title_name_en, report_title_address_cn, report_title_address_en
    )。
    application_no 取标签字面含「申请单号」（且非「分包申请单编号」）那一行的右侧单元格。
    """
    name_cn = ""
    name_en = ""
    address_cn = ""
    address_en = ""
    application_no = ""
    report_title_name_cn = ""
    report_title_name_en = ""
    report_title_address_cn = ""
    report_title_address_en = ""

    payer_name_cn = ""
    payer_name_en = ""
    payer_address_cn = ""
    payer_address_en = ""

    for row in sheet.iter_rows(values_only=True):
        for label_raw, value in _extract_label_value_pairs(row):
            if not _is_valid_field_label(label_raw):
                continue
            if _is_application_no_label(label_raw) and not application_no:
                application_no = value
                continue
            report_title_field = _classify_report_title_pair(label_raw, value)
            if report_title_field:
                lang = applicant_pair_language(label_raw, value)
                from application_parser.field_extract_applicant import split_bilingual_cell
                val_cn, val_en = split_bilingual_cell(value)
                if report_title_field == "name":
                    if lang == "cn":
                        report_title_name_cn = val_cn if val_cn else value
                        if not report_title_name_en and val_en:
                            report_title_name_en = val_en
                    else:
                        report_title_name_en = val_en if val_en else value
                        if not report_title_name_cn and val_cn:
                            report_title_name_cn = val_cn
                elif report_title_field == "address":
                    if lang == "cn":
                        report_title_address_cn = val_cn if val_cn else value
                        if not report_title_address_en and val_en:
                            report_title_address_en = val_en
                    else:
                        report_title_address_en = val_en if val_en else value
                        if not report_title_address_cn and val_cn:
                            report_title_address_cn = val_cn
                continue
            payer_field = classify_payer_pair(label_raw, value)
            if payer_field:
                lang = applicant_pair_language(label_raw, value)
                from application_parser.field_extract_applicant import split_bilingual_cell
                val_cn, val_en = split_bilingual_cell(value)
                if payer_field == "name":
                    if lang == "cn":
                        payer_name_cn = val_cn if val_cn else value
                        if not payer_name_en and val_en:
                            payer_name_en = val_en
                    else:
                        payer_name_en = val_en if val_en else value
                        if not payer_name_cn and val_cn:
                            payer_name_cn = val_cn
                elif payer_field == "address":
                    if lang == "cn":
                        payer_address_cn = val_cn if val_cn else value
                        if not payer_address_en and val_en:
                            payer_address_en = val_en
                    else:
                        payer_address_en = val_en if val_en else value
                        if not payer_address_cn and val_cn:
                            payer_address_cn = val_cn
                continue
            field = classify_applicant_pair(label_raw, value)
            if not field:
                continue
            lang = applicant_pair_language(label_raw, value)
            from application_parser.field_extract_applicant import split_bilingual_cell
            val_cn, val_en = split_bilingual_cell(value)
            if field == "name":
                if lang == "cn":
                    name_cn = val_cn if val_cn else value
                    if not name_en and val_en:
                        name_en = val_en
                else:
                    name_en = val_en if val_en else value
                    if not name_cn and val_cn:
                        name_cn = val_cn
            elif field == "address":
                if lang == "cn":
                    address_cn = val_cn if val_cn else value
                    if not address_en and val_en:
                        address_en = val_en
                else:
                    address_en = val_en if val_en else value
                    if not address_cn and val_cn:
                        address_cn = val_cn

    if is_same_as_applicant_value(name_cn):
        name_cn = name_en if not is_same_as_applicant_value(name_en) else ""
    if is_same_as_applicant_value(name_en):
        name_en = name_cn if name_cn else ""
    if is_same_as_applicant_value(address_cn):
        address_cn = address_en if not is_same_as_applicant_value(address_en) else ""
    if is_same_as_applicant_value(address_en):
        address_en = address_cn if address_cn else ""

    payer_name_cn = resolve_same_as_applicant(
        payer_name_cn,
        field="name",
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
    )
    payer_name_en = resolve_same_as_applicant(
        payer_name_en,
        field="name",
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
    )
    payer_address_cn = resolve_same_as_applicant(
        payer_address_cn,
        field="address",
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
    )
    payer_address_en = resolve_same_as_applicant(
        payer_address_en,
        field="address",
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
    )

    report_title_name_cn = resolve_report_title_reference(
        report_title_name_cn,
        field="name",
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
        payer_name_cn=payer_name_cn,
        payer_name_en=payer_name_en,
        payer_address_cn=payer_address_cn,
        payer_address_en=payer_address_en,
    )
    report_title_name_en = resolve_report_title_reference(
        report_title_name_en,
        field="name",
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
        payer_name_cn=payer_name_cn,
        payer_name_en=payer_name_en,
        payer_address_cn=payer_address_cn,
        payer_address_en=payer_address_en,
    )
    report_title_address_cn = resolve_report_title_reference(
        report_title_address_cn,
        field="address",
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
        payer_name_cn=payer_name_cn,
        payer_name_en=payer_name_en,
        payer_address_cn=payer_address_cn,
        payer_address_en=payer_address_en,
    )
    report_title_address_en = resolve_report_title_reference(
        report_title_address_en,
        field="address",
        applicant_name_cn=name_cn,
        applicant_name_en=name_en,
        applicant_address_cn=address_cn,
        applicant_address_en=address_en,
        payer_name_cn=payer_name_cn,
        payer_name_en=payer_name_en,
        payer_address_cn=payer_address_cn,
        payer_address_en=payer_address_en,
    )

    return (
        name_cn,
        name_en,
        address_cn,
        address_en,
        application_no,
        report_title_name_cn,
        report_title_name_en,
        report_title_address_cn,
        report_title_address_en,
    )


def _is_application_no_label(label: str) -> bool:
    """识别「申请单号」标签，但排除「分包申请单编号」之类的衍生项。

    典型字面：「申请单号(for CTI only)」「申请单号」「Application No.」。
    通过排除关键词「分包」「子单」避开易混项。
    """
    s = (label or "").strip()
    if not s:
        return False
    if "分包" in s or "子单" in s:
        return False
    return "申请单号" in s or "申请单编号" in s


def _expand_multiline_cell_values(val: str) -> List[str]:
    """单元格内换行分隔的多组样品值拆成独立候选（如两个零件号各占一行）。"""
    text = (val or "").strip()
    if not text or "\n" not in text:
        return [text] if text else []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return [text]
    return lines


def _collect_sample_row_candidates(row, *, keep_duplicates: bool = False) -> List[str]:
    """Sheet2 一行中第 2 列起各组样品的非空取值（默认去重，送样数量保留各列）。

    若该行仅有 /、-、无 等空值标记，仍保留这些标记供规则比对（避免整行被丢弃）。
    值列存在但全部空白（未填 /）时保留空串，供规则在报告侧也有该字段时出比对项。
    单元格内换行分隔的多值会拆成多个候选（与分列填写等效）。
    """
    candidates: List[str] = []
    sentinels: List[str] = []
    saw_value_column = False
    for col_idx in range(1, len(row)):
        saw_value_column = True
        val = _cell_str(row[col_idx]) if col_idx < len(row) else ""
        if _is_instruction_text(val):
            continue
        if is_blank_or_slash(val):
            marker = val.strip()
            if marker and marker not in sentinels:
                sentinels.append(marker)
            continue
        pieces = _expand_multiline_cell_values(val)
        for piece in pieces:
            if not keep_duplicates and any(
                values_match(piece, existing) for existing in candidates
            ):
                continue
            candidates.append(piece)
    if candidates:
        return candidates
    if sentinels:
        return sentinels
    # 标签行有样品列但未填任何内容（区别于整表无值列）：记为空串，避免零件号等行被丢弃
    return [""] if saw_value_column else []


def _effective_sample_storage_key(key: str) -> str:
    """Sheet2 行标签 → 样品信息字典键（中文键；英文标签映射到中文）。"""
    key = _normalize_sample_key(key)
    if not key:
        return ""
    if _has_chinese(key):
        return normalize_sample_field_key(key) or key
    return english_sample_field_to_cn(key) or ""


def _should_include_sample_row(key: str, candidates: List[str]) -> bool:
    storage_key = _effective_sample_storage_key(key)
    if not storage_key:
        return False
    if any(skip in storage_key for skip in _SAMPLE_SKIP_KEYS):
        return False
    return bool(candidates)


def parse_application_sheet2(sheet) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """解析 Sheet2：每行标签 + 多列样品值。

    多组样品时各列代表不同样品（001/002/003…），比对时由规则引擎在
    `sample_info_candidates` 中任选匹配列，而非固定第二列。
    中文行下一行的英文标签（如 主机厂 / OEM）会合并到上一中文行的候选值。
    """
    sample_info: Dict[str, str] = {}
    sample_info_candidates: Dict[str, List[str]] = {}
    last_cn_key = ""

    def _store_sample_row(storage_key: str, candidates: List[str]) -> None:
        nonlocal last_cn_key
        if not storage_key or not candidates:
            last_cn_key = ""
            return
        keep_all = is_quantity_sample_field(storage_key)
        existing = sample_info_candidates.get(storage_key) or []
        merged = list(existing)
        for val in candidates:
            if is_blank_or_slash(val):
                if merged and any(not is_blank_or_slash(item) for item in merged):
                    continue
                marker = (val or "").strip()
                if not keep_all and any(values_match(val, item) for item in merged):
                    # 空串与 / 比对等价；后到的显式 /、-、无 应覆盖先写入的空串
                    if marker:
                        for i, item in enumerate(merged):
                            if not (item or "").strip():
                                merged[i] = marker
                                break
                    continue
                merged.append(val)
                continue
            if not keep_all and any(values_match(val, item) for item in merged):
                continue
            merged.append(val)
        sample_info[storage_key] = merged[0]
        sample_info_candidates[storage_key] = merged
        last_cn_key = storage_key

    for row in sheet.iter_rows(values_only=True):
        if not row or not row[0]:
            continue
        key = _normalize_sample_key(_cell_str(row[0]))
        keep_duplicates = is_quantity_sample_field(key) or bool(
            english_sample_field_to_cn(key)
        )
        candidates = _collect_sample_row_candidates(row, keep_duplicates=keep_duplicates)
        storage_key = _effective_sample_storage_key(key)
        if (
            storage_key
            and last_cn_key
            and not _has_chinese(key)
            and sample_storage_keys_alias_equivalent(last_cn_key, storage_key)
        ):
            storage_key = last_cn_key
        if storage_key:
            if _should_include_sample_row(key, candidates):
                _store_sample_row(storage_key, candidates)
            else:
                last_cn_key = ""
            continue
        if last_cn_key and candidates:
            _store_sample_row(last_cn_key, candidates)
    return sample_info, sample_info_candidates


def extract_application_sample_column_names(sheet) -> List[str]:
    """Sheet2 各列样品名称（优先中文「样品名称」行，无则取英文 Sample Name 行）。"""
    cn_names: List[str] = []
    en_names: List[str] = []
    for row in sheet.iter_rows(values_only=True):
        if not row or not row[0]:
            continue
        key = _normalize_sample_key(_cell_str(row[0]))
        storage_key = _effective_sample_storage_key(key)
        if storage_key != "样品名称":
            continue
        cols = _collect_sample_row_candidates(row, keep_duplicates=True)
        if _has_chinese(key):
            cn_names = cols
        elif cn_names:
            en_names = cols
    primary = cn_names or en_names
    return [v.strip() for v in primary if v and not is_blank_or_slash(v)]


def _selection_sheet_sample_key(label: str) -> Optional[str]:
    """「应选信息」页同行双语标签 → 样品信息比对用中文键。"""
    norm = normalize_sample_field_key(label)
    if norm == "主机厂":
        return "主机厂"
    return None


def _bilingual_cell_value_candidates(value: str) -> List[str]:
    """单元格内中英连写（如 长安汽车CCAG）拆成完整值 + 中文段 + 英文段供比对。"""
    val = (value or "").strip()
    if not val or is_blank_or_slash(val):
        return []
    parts: List[str] = [val]
    cn = extract_chinese_text(val)
    if cn and not any(values_match(cn, p) for p in parts):
        parts.append(cn)
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9.\-/]*", val):
        token = m.group(0)
        if len(token) >= 2 and not any(values_match(token, p) for p in parts):
            parts.append(token)
    return parts


def parse_application_selection_sample_fields(sheet) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """解析「申请单应选信息」页中与样品信息表同名的字段（常为单行中英连写）。"""
    sample_info: Dict[str, str] = {}
    sample_info_candidates: Dict[str, List[str]] = {}
    for row in sheet.iter_rows(values_only=True):
        for label_raw, value in _extract_label_value_pairs(row):
            if not _is_valid_field_label(label_raw) or _is_instruction_text(value):
                continue
            key = _selection_sheet_sample_key(label_raw)
            if not key:
                continue
            candidates = _bilingual_cell_value_candidates(value)
            if not candidates:
                continue
            sample_info[key] = candidates[0]
            sample_info_candidates[key] = candidates
    return sample_info, sample_info_candidates


def _prefer_selection_sheet_over_sheet2(
    selection_value: str,
    sheet2_candidates: List[str],
) -> bool:
    """第二页拆行值均落在第一页同一格内时，以应选信息页为准。"""
    if not (selection_value or "").strip():
        return False
    active = [c for c in sheet2_candidates if not is_blank_or_slash(c)]
    if not active:
        return True
    return _all_candidates_contained_in_report(active, selection_value)


def parse_application(file_bytes: bytes, filename: str, *, volvo: bool = False) -> ApplicationData:
    if volvo:
        from application_parser.excel_volvo import parse_volvo_application

        return parse_volvo_application(file_bytes, filename)

    wb = load_workbook_from_bytes(file_bytes, data_only=True)
    filename = normalize_upload_filename(filename) or "application.xlsx"

    sheet1 = find_application_selection_sheet(wb)
    name_cn = name_en = address_cn = address_en = ""
    application_no = ""
    report_title_name_cn = report_title_name_en = ""
    report_title_address_cn = report_title_address_en = ""
    if sheet1:
        (
            name_cn,
            name_en,
            address_cn,
            address_en,
            application_no,
            report_title_name_cn,
            report_title_name_en,
            report_title_address_cn,
            report_title_address_en,
        ) = parse_application_sheet1(sheet1)
    applicant_name = name_cn or name_en
    applicant_address = address_cn or address_en

    sample_info: Dict[str, str] = {}
    sample_info_candidates: Dict[str, List[str]] = {}
    sample_column_names: List[str] = []
    sheet2 = find_application_sample_sheet(wb)
    if sheet2:
        sample_info, sample_info_candidates = parse_application_sheet2(sheet2)
        sample_column_names = extract_application_sample_column_names(sheet2)
    if sheet1:
        sel_info, sel_cands = parse_application_selection_sample_fields(sheet1)
        for key, val in sel_info.items():
            sheet2_cands = sample_info_candidates.get(key)
            if sheet2_cands is None and key in sample_info:
                sheet2_cands = [sample_info[key]]
            if _prefer_selection_sheet_over_sheet2(val, sheet2_cands or []):
                sample_info[key] = val
                sample_info_candidates[key] = sel_cands[key]
    # 申请单号在 Sheet1（B3），但下游 applicant 规则按 sample_info 字典遍历来比对，
    # 这里把它放到 dict 最前面，让「申请单号 vs 报告编号前 12 位」比对回到结果列表顶部。
    if application_no:
        sample_info = {"申请单号": application_no, **sample_info}
        sample_info_candidates = {"申请单号": [application_no], **sample_info_candidates}

    # 本导出包故意不解析第 3 页「测试信息 / 试验项目」。
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
        sample_column_names=sample_column_names,
    )
