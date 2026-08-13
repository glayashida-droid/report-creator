"""英文报告识别与申请单/报告字段语言侧选择。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from application_parser.field_extract_labels import (
    _CHINESE_RE,
    _ENGLISH_ROW_MARKERS,
    pick_by_report_language,
)


def _is_english_only_label(label: str) -> bool:
    norm = (label or "").strip()
    lower = norm.lower()
    if "★" in norm:
        return True
    if _CHINESE_RE.search(norm):
        return False
    return any(m in lower for m in _ENGLISH_ROW_MARKERS) or bool(
        re.match(r"^[A-Za-z\s./]+$", norm)
    )

# 申请单 Sheet2 纯英文标签 → 样品信息比对用中文键（与 field_extract_match 别名一致）
_ENGLISH_SAMPLE_KEY_TO_CN: Dict[str, str] = {
    "samplename": "样品名称",
    "name": "样品名称",
    "samplestate": "样品状态",
    "state": "样品状态",
    "samplecharacteristics": "样品特性",
    "characteristics": "样品特性",
    "hazard": "样品特性",
    "partno": "零件号",
    "partnumber": "零件号",
    "partno.": "零件号",
    "material": "材料牌号",
    "materialcode": "材料牌号",
    "materialtrademark": "材料牌号",
    "materialno": "材料牌号",
    "materialnumber": "材料牌号",
    "model": "车型",
    "vehiclemodel": "车型",
    "projectcode": "车型项目",
    "projectphase": "项目阶段",
    "projectverification": "项目阶段",
    "quantityofsamples": "送样数量",
    "quantityofsample": "送样数量",
    "quantity": "送样数量",
    "no.ofsamples": "送样数量",
    "oem": "主机厂",
    "manufacturer": "生产商",
    "applicationno": "申请单号",
    "reportno": "申请单号",
}

_HOMEPAGE_EN_LABEL_MARKERS = (
    "customer",
    "address shown",
    "applicant address",
    "applicant name",
    "quantity of sample",
    "sample name",
    "sample received",
    "testing period",
)


def _compact_field_key(key: str) -> str:
    raw = (key or "").strip().lstrip("★* ").lower()
    return re.sub(r"[\s:：._\-/]+", "", raw)


def english_sample_field_to_cn(key: str) -> Optional[str]:
    """Sheet2 英文行标签映射到样品信息中文键。"""
    compact = _compact_field_key(key)
    if not compact:
        return None
    if compact in _ENGLISH_SAMPLE_KEY_TO_CN:
        return _ENGLISH_SAMPLE_KEY_TO_CN[compact]
    for frag, cn in _ENGLISH_SAMPLE_KEY_TO_CN.items():
        if len(frag) >= 6 and frag in compact:
            return cn
    return None


def filename_suggests_english_report(filename: str) -> bool:
    """文件名主干以数字结尾、末尾无字母 → 常见英文版报告命名。"""
    stem = Path((filename or "").strip()).stem
    if not stem:
        return False
    tail = stem.rstrip()
    if not tail or not tail[-1].isdigit():
        return False
    return not bool(re.search(r"[A-Za-z]$", tail))


def homepage_labels_suggest_english(labels: Iterable[str]) -> bool:
    """首页表左列多为 Customer / Address 等纯英文标签。"""
    items = [l for l in labels if (l or "").strip()]
    if not items:
        return False
    en_only = sum(1 for l in items if _is_english_only_label(l))
    cn_any = sum(1 for l in items if _CHINESE_RE.search(l))
    if en_only >= 2 and cn_any == 0:
        return True
    lower_joined = " ".join(l.lower() for l in items)
    marker_hits = sum(1 for m in _HOMEPAGE_EN_LABEL_MARKERS if m in lower_joined)
    return marker_hits >= 2 and cn_any == 0


def detect_english_report(
    filename: str,
    sample_info: Dict[str, str],
    *,
    extra_labels: Optional[Iterable[str]] = None,
) -> bool:
    labels = list(sample_info.keys()) + list(extra_labels or [])
    if filename_suggests_english_report(filename):
        return True
    return homepage_labels_suggest_english(labels)


def report_value_prefers_english(report_value: str) -> bool:
    v = (report_value or "").strip()
    return bool(v) and not _CHINESE_RE.search(v)


def ordered_application_candidates(
    candidates: List[str], report_value: str, *, english_report: bool = False
) -> List[str]:
    """英文报告优先用申请单英文候选行比对。"""
    if not english_report and not report_value_prefers_english(report_value):
        return candidates
    en_first = [c for c in candidates if c and not _CHINESE_RE.search(c)]
    rest = [c for c in candidates if c not in en_first]
    return en_first + rest if en_first else candidates


def pick_application_value_for_report(
    candidates: List[str], report_value: str, *, english_report: bool = False
) -> str:
    ordered = ordered_application_candidates(
        candidates, report_value, english_report=english_report
    )
    if not ordered:
        return ""
    cn_vals = [c for c in ordered if _CHINESE_RE.search(c)]
    en_vals = [c for c in ordered if c and not _CHINESE_RE.search(c)]
    return pick_by_report_language(
        cn_vals[0] if cn_vals else "",
        en_vals[0] if en_vals else "",
        report_value,
    ) or ordered[0]
