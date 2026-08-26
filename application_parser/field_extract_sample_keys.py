"""样品信息字段别名、键兼容与 sample_info 查找。"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from application_parser.field_extract_labels import (
    clean_label,
    normalize_sample_field_key,
)
from application_parser.field_extract_quantity import (
    is_quantity_sample_field,
    quantity_candidates_total,
)
from application_parser.field_extract_values import (
    format_sample_field_display,
    is_blank_or_slash,
)

# Keys in application sheet2 that must not be compared
SAMPLE_COMPARE_SKIP = (
    "样品序号",
    "申请单样品需要",
    "样品特性",
    "工艺",
    "是否有",
    "供应商代码",
    "送样数量",
)

# 申请单 Sheet2：项目代码 / 车型代码 / ★车型项目 / Project Code 视为同一存储语义（解析合并用）
_PROJECT_CODE_STORAGE_KEYS = frozenset({"项目代码", "车型代码", "车型项目"})
_VEHICLE_MODEL_KEY = "车型"

# Map application field -> report table label keywords (after clean_label)
SAMPLE_FIELD_ALIASES: Dict[str, Tuple[str, ...]] = {
    "样品名称": ("样品名称", "Sample Name", "Name of sample", "sample name"),
    "样品状态": ("样品状态", "状态", "Sample State", "State", "sample state"),
    "样品特性": ("样品特性", "特性", "Hazard", "hazard", "Sample Characteristics"),
    "颜色": ("颜色", "Color", "Colour"),
    "车型": ("车型", "型号", "model", "Vehicle Model", "Model"),
    "项目代码": ("项目代码", "车型代码", "Project Code", "车型项目"),
    "车型代码": ("车型代码", "项目代码", "车型项目", "Project Code"),
    "车型项目": ("车型项目", "项目代码", "车型代码", "Project Code"),
    "申请单号": ("申请单号", "报告编号", "Application No", "Report No"),
    "零件号": ("零件号", "样品零件号", "part", "Part No", "Part Number"),
    # Material / Material Code / Material Trademark are distinct application rows.
    "材料编号": (
        "材料编号",
        "Material Code",
        "Material No",
        "Material Number",
    ),
    "材质": ("材质", "Material"),
    "材料牌号": ("材料牌号", "Material Trademark"),
    "生产日期": ("生产日期", "Production Date", "Date of Production"),
    "样品批号": ("样品批号", "Sample Batch", "Batch No", "Batch Number"),
    "项目阶段": (
        "项目阶段",
        "project",
        "Project Phase",
        "project phase",
        "Project Verification",
    ),
    "送样数量": (
        "送样数量",
        "客户送样数量",
        "Quantity of sample",
        "Quantity of samples",
        "quantity of sample supplied",
    ),
    "主机厂": ("主机厂", "OEM"),
    "买家": ("买家", "Buyer", "主机厂", "OEM"),
    "生产单位": (
        "生产单位",
        "生产厂",
        "生产厂家",
        "Manufacturer",
        "Producer",
        "生产商",
    ),
    "供应商": ("供应商", "Supplier", "生产商", "Producer"),
    "实验目的": ("实验目的", "试验目的", "检测目的"),
    "试验类型": ("试验类型", "检测类型", "Test Type", "test type"),
    "检测类型": ("检测类型", "试验类型", "Test Type", "test type"),
}

def _sample_field_key_compatible(left: str, right: str) -> bool:
    """报告表头键与申请单/别名键是否可比对（禁止 车型 ↔ 项目代码/车型项目 子串误配）。"""
    lk = normalize_sample_field_key(left)
    rk = normalize_sample_field_key(right)
    if not lk or not rk:
        return False
    if lk == rk:
        return True
    if _VEHICLE_MODEL_KEY in (lk, rk) and (
        lk in _PROJECT_CODE_STORAGE_KEYS or rk in _PROJECT_CODE_STORAGE_KEYS
    ):
        return False
    # 「材料」与「材料牌号/基材材质牌号」是申请单上不同行，禁止子串误配
    if (lk == "材料" or rk == "材料") and ("牌号" in lk or "牌号" in rk):
        return False
    if lk != rk:
        shorter, longer = (lk, rk) if len(lk) <= len(rk) else (rk, lk)
        if longer.startswith(shorter):
            remainder = clean_label(longer[len(shorter) :])
            # 如 车型 + 生产日期 被连写成 车型生产日期
            if remainder and remainder != shorter:
                return False
    return lk in rk or rk in lk


def sample_field_alias_keys(app_key: str) -> Tuple[str, ...]:
    """字段键所属别名组（含 canonical），用于申请单双语行与报告键互查。"""
    norm = normalize_sample_field_key(app_key)
    if not norm:
        return ()
    if norm in SAMPLE_FIELD_ALIASES:
        canonical = norm
        return (canonical, *SAMPLE_FIELD_ALIASES[canonical])
    for canonical, aliases in SAMPLE_FIELD_ALIASES.items():
        alias_keys = {canonical, *(normalize_sample_field_key(x) for x in aliases)}
        if norm in alias_keys:
            return (canonical, *aliases)
    return (norm,)


def sample_storage_keys_alias_equivalent(key_a: str, key_b: str) -> bool:
    """中文行与紧随英文行是否同一字段（如 项目代码 + Project Code、★车型项目 + Project Code）。"""
    a = normalize_sample_field_key(key_a)
    b = normalize_sample_field_key(key_b)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in _PROJECT_CODE_STORAGE_KEYS and b in _PROJECT_CODE_STORAGE_KEYS:
        return True
    for canonical, aliases in SAMPLE_FIELD_ALIASES.items():
        alias_keys = {canonical, *(normalize_sample_field_key(x) for x in aliases)}
        if a in alias_keys and b in alias_keys:
            return True
    return False


def should_compare_sample_field(app_key: str) -> bool:
    key = clean_label(app_key)
    return not any(skip in key for skip in SAMPLE_COMPARE_SKIP)

def format_application_row_reference(field_key: str, candidates: List[str]) -> str:
    if not candidates:
        return f"{field_key}："
    if is_quantity_sample_field(field_key) and len(candidates) > 1:
        total = quantity_candidates_total(candidates)
        if total is not None:
            parts = " + ".join(format_sample_field_display(c) for c in candidates)
            return f"{field_key}（申请单各组样品）：{parts}（合计 {total}）"
    if len(candidates) == 1:
        val = candidates[0]
        return f"{field_key}：{format_sample_field_display(val)}"
    primary = candidates[0]
    primary_compact = re.sub(r"[\s\-_/]+", "", primary or "")
    if primary_compact and all(
        is_blank_or_slash(c)
        or re.sub(r"[\s\-_/]+", "", c) in primary_compact
        or re.sub(r"[\s\-_/]+", "", c).upper() in primary_compact.upper()
        for c in candidates[1:]
    ):
        return f"{field_key}：{format_sample_field_display(primary)}"
    opts = " / ".join(format_sample_field_display(c) for c in candidates)
    return f"{field_key}（申请单各组样品）：{opts}"


def ensure_quantity_in_sample_info(
    sample_info: dict, total: int, *, display: str = ""
) -> None:
    """首页送样数常写入 total_samples；第 8 条比对读 sample_info，需补全别名键。"""
    if total <= 0:
        return
    if find_sample_value(sample_info, "送样数量") is not None:
        return
    text = (display or "").strip() or str(total)
    for key in ("送样数量", "客户送样数量"):
        sample_info.setdefault(key, text)


def sample_fields_equivalent_for_lookup(app_key: str, report_key: str) -> bool:
    """申请单字段键与报告字段键是否指向同一样品信息项。"""
    app_clean = normalize_sample_field_key(app_key)
    rep_clean = normalize_sample_field_key(report_key)
    if not app_clean or not rep_clean:
        return False
    if _sample_field_key_compatible(app_clean, rep_clean):
        return True
    app_group = {normalize_sample_field_key(x) for x in sample_field_alias_keys(app_key)}
    rep_group = {normalize_sample_field_key(x) for x in sample_field_alias_keys(report_key)}
    if not app_group or not rep_group:
        return False
    return bool(app_group & rep_group)


def find_sample_entry(sample_info: dict, app_key: str) -> Tuple[Optional[str], Optional[str]]:
    """同 find_sample_value，但同时返回命中的报告字段键，供按报告原文语言展示标签。"""
    if app_key in sample_info:
        return sample_info[app_key], app_key

    app_key_clean = normalize_sample_field_key(app_key)
    aliases = sample_field_alias_keys(app_key) or (app_key_clean,)

    for alias in aliases:
        alias_clean = normalize_sample_field_key(alias)
        if alias in sample_info and _sample_field_key_compatible(app_key_clean, alias_clean):
            return sample_info[alias], alias

    for report_key, value in sample_info.items():
        if sample_fields_equivalent_for_lookup(app_key, report_key):
            return value, report_key
    return None, None


def find_sample_value(sample_info: dict, app_key: str) -> Optional[str]:
    return find_sample_entry(sample_info, app_key)[0]
