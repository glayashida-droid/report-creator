"""申请单包内对报告侧辅助函数的占位，避免拉入 Word/LLM 依赖。

本包只解析申请单；下列函数仅在「字段匹配」辅助模块里被惰性引用，
正常 parse_application 路径不会走到报告结果表逻辑。
"""

from __future__ import annotations

import re


def is_result_description_column(key: str) -> bool:
    if not key:
        return False
    lower = key.lower()
    return "结果" in key or "result" in lower or "description" in lower


def extract_value_portion(text: str) -> str:
    """从单元格/片段中取「值」：若有冒号，取第一个冒号之后。"""
    text = (text or "").strip()
    if not text or text in (":", "：", "|"):
        return ""
    if "|" in text:
        right = text.split("|", 1)[-1]
        right = re.sub(r"^[\s:：|]+", "", right).strip()
        if right:
            return extract_value_portion(right)
    for sep in (":", "："):
        idx = text.find(sep)
        if idx >= 0:
            val = text[idx + 1 :].strip()
            if val and val not in (":", "："):
                return val
    return re.sub(r"^[\s:：|]+", "", text).strip()
