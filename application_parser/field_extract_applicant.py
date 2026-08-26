"""委托方 Sheet1 字段识别、双语行判定与同申请人占位解析。"""
from __future__ import annotations

import re
from typing import List, Optional

from application_parser.field_extract_labels import (
    _CHINESE_RE,
    _ENGLISH_ROW_MARKERS,
    _collapse_label_spaces,
    clean_label,
)
from application_parser.field_extract_match import values_match

_SAME_AS_APPLICANT_RE = re.compile(
    r"同(?:被)?申请(?:公司|单位)?(?:地址)?|same\s*as\s*applicant",
    re.IGNORECASE,
)

_SAME_AS_PAYER_RE = re.compile(
    r"同付款(?:公司|单位)?(?:地址)?|same\s*as\s*payer",
    re.IGNORECASE,
)


def _is_instruction_text(text: str, *, label: str = "") -> bool:
    label_norm = _collapse_label_spaces((label or "").strip())
    lower = label_norm.lower()
    if "地址" in label_norm or ("address" in lower and "name" not in lower):
        return len(text or "") > 500
    if len(text) > 80:
        return True
    if re.match(r"^\d+[、.．]", text):
        return True
    markers = ("必填", "邮寄", "退回处理", "包装外部", "表中的", "均需要")
    return sum(1 for m in markers if m in text) >= 2


def _looks_like_model_code_suffix(en: str) -> bool:
    """英文段更像型号/零件后缀（如 ADCU8、PA66），而非「黑色Black」/地址译文。

    仅拦截「无空白、无英文句读」的紧凑字母数字串；
    「No. 888, …」这类带空格/标点的地址英文段仍按中英连写拆开。
    """
    token = (en or "").strip()
    if not token:
        return False
    if re.search(r"[\s.,;:]", token):
        return False
    return bool(re.search(r"\d", token) and re.search(r"[A-Za-z]", token))


def _split_inline_bilingual(value: str) -> tuple[str, str] | None:
    """中英文连写（无换行/斜杠）时，按首个英文词切分。

    不含数字的译文后缀（黑色Black / 长安汽车CCAG）可拆；
    含数字的型号后缀（自动驾驶域控制器ADCU8）保持原串。
    """
    if not _CHINESE_RE.search(value) or not re.search(r"[A-Za-z]{2}", value):
        return None
    for m in re.finditer(r"[A-Za-z]{2}", value):
        pos = m.start()
        cn = value[:pos].strip()
        en = value[pos:].strip()
        if not cn or not en:
            continue
        if not _CHINESE_RE.search(cn) or _CHINESE_RE.search(en):
            continue
        if _looks_like_model_code_suffix(en):
            continue
        return cn, en
    return None


def split_bilingual_cell(value: str) -> tuple[str, str]:
    """同单元格中英分行（或斜杠分隔） → (中文段, 英文段)。"""
    value = (value or "").strip()
    if not value:
        return "", ""
        
    parts = []
    is_newline = "\n" in value
    if is_newline:
        parts = [p.strip() for p in value.split("\n") if p.strip()]
    elif "/" in value:
        split_parts = [p.strip() for p in value.split("/") if p.strip()]
        if len(split_parts) == 2:
            parts = split_parts
        elif len(split_parts) > 2:
            for i in range(1, len(split_parts)):
                left = "/".join(split_parts[:i])
                right = "/".join(split_parts[i:])
                if _CHINESE_RE.search(left) and not _CHINESE_RE.search(right):
                    parts = [left, right]
                    break
            if not parts:
                parts = [value]
        else:
            parts = [value]

    if len(parts) >= 2:
        cn_parts = [p for p in parts if _CHINESE_RE.search(p)]
        en_parts = [p for p in parts if not _CHINESE_RE.search(p)]
        
        if cn_parts and en_parts:
            cn = "\n".join(cn_parts)
            en = "\n".join(en_parts)
            return cn, en
            
        if is_newline:
            cn = "\n".join(cn_parts) if cn_parts else parts[0]
            en = "\n".join(en_parts) if en_parts else (parts[-1] if len(parts) > 1 else "")
            if _CHINESE_RE.search(value):
                return value, en if en_parts else ""
            return "", value

    inline = _split_inline_bilingual(value)
    if inline:
        return inline
    if _CHINESE_RE.search(value):
        return value, ""
    return "", value


def _is_blocked_applicant_label(label: str) -> bool:
    norm = _collapse_label_spaces((label or "").strip())
    lower = norm.lower()
    blocked = (
        "payer",
        "invoice",
        "express",
        "report delivery",
        "contact",
        "e-mail",
        "email",
        "收报告",
        "寄送",
        "company shown",
        "shown on report",
        "same as applicant",
        "同申请公司",
        "同被申请",
        "抬头",
        "送报告",
        "送发票",
        "取报告",
        "hard copy",
        "report format",
        "report language",
        "service type",
    )
    return any(b in lower or b in norm for b in blocked)


def is_same_as_applicant_value(value: str) -> bool:
    return bool(_SAME_AS_APPLICANT_RE.search((value or "").strip()))


def is_same_as_payer_value(value: str) -> bool:
    return bool(_SAME_AS_PAYER_RE.search((value or "").strip()))


def _prefer_english_side(side: str) -> bool:
    s = (side or "cn").strip().lower()
    return s in ("en", "英文", "english")


def resolve_same_as_applicant(
    value: str,
    *,
    field: str,
    applicant_name_cn: str,
    applicant_name_en: str,
    applicant_address_cn: str,
    applicant_address_en: str,
    side: str = "cn",
) -> str:
    """占位「同申请公司」→ 回填申请公司名/地址。

    ``side="en"`` 只取英文侧（缺英留空，不回退中文）。
    """
    if not is_same_as_applicant_value(value):
        return value
    prefer_en = _prefer_english_side(side)
    if field == "name":
        if prefer_en:
            return (applicant_name_en or "").strip()
        return applicant_name_cn or applicant_name_en
    if prefer_en:
        return (applicant_address_en or "").strip()
    return applicant_address_cn or applicant_address_en


def resolve_same_as_payer(
    value: str,
    *,
    field: str,
    payer_name_cn: str,
    payer_name_en: str,
    payer_address_cn: str,
    payer_address_en: str,
    side: str = "cn",
) -> str:
    """占位「同付款公司」→ 回填付款公司名/地址（不是申请公司）。"""
    if not is_same_as_payer_value(value):
        return value
    prefer_en = _prefer_english_side(side)
    if field == "name":
        if prefer_en:
            return (payer_name_en or "").strip()
        return payer_name_cn or payer_name_en
    if prefer_en:
        return (payer_address_en or "").strip()
    return payer_address_cn or payer_address_en


def resolve_report_title_reference(
    value: str,
    *,
    field: str,
    applicant_name_cn: str,
    applicant_name_en: str,
    applicant_address_cn: str,
    applicant_address_en: str,
    payer_name_cn: str,
    payer_name_en: str,
    payer_address_cn: str,
    payer_address_en: str,
    side: str = "cn",
) -> str:
    """报告抬头占位解析：同申请公司→申请公司；同付款公司→付款公司。"""
    value = resolve_same_as_applicant(
        value,
        field=field,
        applicant_name_cn=applicant_name_cn,
        applicant_name_en=applicant_name_en,
        applicant_address_cn=applicant_address_cn,
        applicant_address_en=applicant_address_en,
        side=side,
    )
    return resolve_same_as_payer(
        value,
        field=field,
        payer_name_cn=payer_name_cn,
        payer_name_en=payer_name_en,
        payer_address_cn=payer_address_cn,
        payer_address_en=payer_address_en,
        side=side,
    )


def classify_payer_pair(label: str, value: str) -> Optional[str]:
    label = (label or "").strip().lstrip("★* ")
    label_norm = _collapse_label_spaces(label)
    value = (value or "").strip()
    if not label or not value or _is_instruction_text(value):
        return None

    lower = label.lower()
    if "付款" not in label_norm and "payer" not in lower:
        return None
    if any(
        b in lower or b in label_norm
        for b in ("invoice", "express", "report", "发票", "寄送", "抬头")
    ):
        return None

    if "地址" in label_norm or ("address" in lower and "name" not in lower):
        return "address"
    if "公司" in label_norm or "payer" in lower:
        return "name"
    return None


def classify_applicant_pair(label: str, value: str) -> Optional[str]:
    label = (label or "").strip().lstrip("★* ")
    label_norm = _collapse_label_spaces(label)
    value = (value or "").strip()
    if not label or not value or _is_instruction_text(value, label=label):
        return None
    if is_same_as_applicant_value(value):
        return None
    if _is_blocked_applicant_label(label):
        return None
    if "确认" in label_norm or "confirmed" in label.lower():
        return None

    lower = label.lower()
    if "地址" in label_norm or ("address" in lower and "name" not in lower):
        return "address"

    name_keywords = (
        "被申请公司",
        "申请公司",
        "申请单位",
        "委托单位",
        "委托方",
        "customer",
        "applicant name",
    )
    if any(k in label or k in lower for k in name_keywords):
        if "地址" not in label:
            return "name"
    if "customer" in lower and "地址" not in label:
        return "name"
    if "applicant name" in lower:
        return "name"
    return None


def applicant_pair_language(label: str, value: str) -> str:
    label = label or ""
    value = value or ""
    core_label = _collapse_label_spaces(label.lstrip("★* "))
    if "★" in label and not _CHINESE_RE.search(core_label):
        return "en"
    if _CHINESE_RE.search(value):
        return "cn"
    if _CHINESE_RE.search(core_label) and not _CHINESE_RE.search(value):
        return "en"
    return "en"


def applicant_bilingual_match(
    app_cn: str,
    app_en: str,
    rep_cn: str,
    rep_en: str,
    *,
    english_report: bool = False,
) -> bool:
    app_cn = (app_cn or "").strip()
    app_en = (app_en or "").strip()
    rep_cn = (rep_cn or "").strip()
    rep_en = (rep_en or "").strip()

    if english_report:
        if rep_en or app_en:
            return values_match(app_en, rep_en)
        return values_match(app_cn or app_en, rep_cn or rep_en)

    # 报告侧有哪些语言就比哪些，不要求中英同时存在。
    checks: list[bool] = []
    if rep_cn:
        checks.append(values_match(app_cn, rep_cn))
    if rep_en:
        checks.append(values_match(app_en, rep_en))
    if checks:
        return all(checks)
    return values_match(app_cn or app_en, rep_cn or rep_en)


def format_applicant_compare_text(cn: str, en: str, *, prefix: str = "") -> str:
    lines: List[str] = []
    p = f"{prefix}" if prefix else ""
    if cn:
        lines.append(f"{p}中文：{cn}" if p else cn)
    if en:
        lines.append(f"{p}英文：{en}" if p else en)
    return "\n".join(lines) if lines else ""


def is_english_only_label(label: str) -> bool:
    norm = (label or "").strip()
    lower = norm.lower()
    if "★" in norm:
        return True
    if _CHINESE_RE.search(norm):
        return False
    return any(m in lower for m in _ENGLISH_ROW_MARKERS) or bool(
        re.match(r"^[A-Za-z\s./]+$", norm)
    )
