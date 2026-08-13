"""样品/样件编号列用语（申请单包精简版：仅保留 is_result_sample_column_key 所需）。"""

from __future__ import annotations

import re

LABEL_YANGPIN = "样品编号"
LABEL_YANGJIAN = "样件编号"

_SAMPLE_ID_KEY_RE = re.compile(
    r"样品编号|样件编号|sample\s*no|sample\s*id|number\s*of\s*sample",
    re.I,
)
_SAMPLE_NAME_COL_RE = re.compile(r"样品名称|sample\s*name", re.I)


def is_sample_id_column_key(key: str) -> bool:
    return bool(key and _SAMPLE_ID_KEY_RE.search(key))


def is_sample_name_column_key(key: str) -> bool:
    return bool(key and _SAMPLE_NAME_COL_RE.search(key))


def is_result_sample_column_key(key: str) -> bool:
    """结果表中的样品列：正式编号列，或误标为「样品名称」的列。"""
    return is_sample_id_column_key(key) or is_sample_name_column_key(key)
