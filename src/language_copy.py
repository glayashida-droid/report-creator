"""Language-side copy helpers shared by edit UI and Word export (seam 2)."""

from __future__ import annotations

import re
from typing import Union

from src.models.project_state import TestResult

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_DEFAULT_PHOTO_STEM = re.compile(r"^(.+)-(\d+)$")

_CONCLUSION_ZH = {
    TestResult.PASS: "合格",
    TestResult.FAIL: "不合格",
    TestResult.NA: "N/A",
}
_CONCLUSION_EN = {
    TestResult.PASS: "Pass",
    TestResult.FAIL: "Fail",
    TestResult.NA: "N/A",
}

_ALBUM_CAPTION_ZH = {
    "试验前": "试验前",
    "试验中": "试验中",
    "试验后": "试验后",
}
_ALBUM_CAPTION_EN = {
    "试验前": "Before test",
    "试验中": "Test setup",
    "试验后": "After test",
}

_RESULT_ALIASES = {
    "Pass": TestResult.PASS,
    "Fail": TestResult.FAIL,
    "合格": TestResult.PASS,
    "不合格": TestResult.FAIL,
    "N/A": TestResult.NA,
    "NA": TestResult.NA,
}


def has_chinese(text: str) -> bool:
    return bool(_CHINESE_RE.search(text or ""))


def _normalize_result(value: Union[TestResult, str, None]) -> TestResult | None:
    if isinstance(value, TestResult):
        return value
    if value is None:
        return None
    key = str(value).strip()
    if key in _RESULT_ALIASES:
        return _RESULT_ALIASES[key]
    try:
        return TestResult(key)
    except ValueError:
        return None


def format_conclusion(result: Union[TestResult, str, None], language: str) -> str:
    """Map 合格/不合格/N/A ↔ Pass/Fail/N/A; bilingual keeps plain N/A."""
    normalized = _normalize_result(result)
    if normalized is None:
        return ""
    zh = _CONCLUSION_ZH[normalized]
    en = _CONCLUSION_EN[normalized]
    lang = (language or "中文").strip()
    if lang == "英文":
        return en
    if lang == "中英文":
        if normalized is TestResult.NA:
            return "N/A"
        return f"{zh} / {en}"
    return zh


def language_text(cn: str, en: str, language: str) -> str:
    """Pick/join sides by report or edit language. English never falls back to Chinese."""
    cn = (cn or "").strip()
    en = (en or "").strip()
    lang = (language or "中文").strip()
    if lang == "英文":
        return en
    if lang == "中英文":
        if cn and en:
            if cn == en:
                return cn
            return f"{cn} / {en}"
        return cn or en
    return cn


def raw_label(zh: str, en: str, language: str) -> str:
    """Fixed UI/table labels: bilingual is raw concat (样品名称Sample Name), no slash."""
    zh = (zh or "").strip()
    en = (en or "").strip()
    lang = (language or "中文").strip()
    if lang == "英文":
        return en
    if lang == "中英文":
        if zh and en:
            return f"{zh}{en}"
        return zh or en
    return zh


def english_from_application(cn_value: str, en_value: str = "") -> str:
    """Prefer explicit EN (must be Han-free); else a CN value with no Han may serve as EN."""
    en = (en_value or "").strip()
    if en and not has_chinese(en):
        return en
    cn = (cn_value or "").strip()
    if cn and not has_chinese(cn):
        return cn
    return ""


# Known overview / sample-info labels → (zh, en)
# Phrasing matches 申请单英文行 / report sample-info table (same seam for edit UI + export).
FIELD_LABELS = {
    "申请单号": ("申请单号", "Application No."),
    "申请公司": ("申请公司", "Applicant Name"),
    "申请公司地址": ("申请公司地址", "Applicant Address"),
    "报告抬头公司": ("报告抬头公司", "Company shown on report"),
    "报告抬头地址": ("报告抬头地址", "Address shown on report"),
    "样品名称": ("样品名称", "Sample Name"),
    "零件号": ("零件号", "Part No."),
    "样品状态": ("样品状态", "Sample State"),
    "样品特性": ("样品特性", "Sample Characteristics"),
    "颜色": ("颜色", "Color"),
    "材料编号": ("材料编号", "Material Code"),
    "材质": ("材质", "Material"),
    "材料牌号": ("材料牌号", "Material Trademark"),
    "生产日期": ("生产日期", "Production Date"),
    "样品批号": ("样品批号", "Sample Batch"),
    "车型": ("车型", "Model"),
    "车型项目": ("车型项目", "Project Code"),
    "项目代码": ("项目代码", "Project Code"),
    "车型代码": ("车型代码", "Project Code"),
    "项目阶段": ("项目阶段", "Project Phase"),
    "送样数量": ("送样数量", "Quantity of Samples"),
    "客户送样数量": ("客户送样数量", "Quantity of Samples"),
    "主机厂": ("主机厂", "OEM"),
    "买家": ("买家", "Buyer"),
    "生产商": ("生产商", "Manufacturer"),
    "生产单位": ("生产单位", "Manufacturer"),
    "供应商": ("供应商", "Supplier"),
    "实验目的": ("实验目的", "Test Purpose"),
    "试验类型": ("试验类型", "Test Type"),
    "检测类型": ("检测类型", "Test Type"),
    "样品接收日期": ("样品接收日期", "Sample Received Date"),
    "样品检测日期": ("样品检测日期", "Testing Period"),
    # Overview date-bar only; report sample-info still uses 样品检测日期 / Testing Period
    "检测开始": ("试验开始", "Test Start"),
    "检测结束": ("试验结束", "Test End"),
    "检测天数": ("天数", "Days"),
}


def field_label(key: str, language: str) -> str:
    """Label for a sample-info / table field. Unknown keys: zh as-is, en empty, ze zh-only."""
    key = (key or "").strip()
    pair = FIELD_LABELS.get(key)
    lang = (language or "中文").strip()
    if pair:
        return raw_label(pair[0], pair[1], lang)
    if lang == "英文":
        return ""
    return key


def is_custom_photo_stem(album: str, file_stem: str) -> bool:
    """True when stem is not the auto `{相册}-序号` form for a template album."""
    album = (album or "").strip()
    stem = (file_stem or "").strip()
    if not album or not stem:
        return bool(stem)
    if album not in _ALBUM_CAPTION_ZH:
        return True
    match = _DEFAULT_PHOTO_STEM.match(stem)
    return not (match and match.group(1) == album)


def photo_caption(album: str, language: str, file_stem: str | None = None) -> str:
    """Caption for a photo: template album defaults by language, else filename stem.

    Custom stems override the default album caption. 「数据」 and unknown albums
    always use the filename strategy (stem or empty).
    """
    album = (album or "").strip()
    stem = (file_stem or "").strip()
    lang = (language or "中文").strip()

    if album in _ALBUM_CAPTION_ZH:
        if stem and is_custom_photo_stem(album, stem):
            return stem
        zh = _ALBUM_CAPTION_ZH[album]
        en = _ALBUM_CAPTION_EN[album]
        return language_text(zh, en, lang)

    return stem
