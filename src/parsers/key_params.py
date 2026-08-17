from __future__ import annotations

import re
from typing import List, Sequence

_SPLIT = re.compile(r"[,，]")


class KeyParamReplaceError(ValueError):
    def __init__(self, missing: Sequence[str]):
        self.missing = [item for item in missing if item]
        preview = "、".join(self.missing)
        super().__init__(f"标准原文中未找到关键参数：{preview}")


def parse_key_params(value) -> List[str]:
    """Split the library 关键参数 cell on comma / Chinese comma."""
    if value is None:
        return []
    text = str(value).strip()
    if text in {"", "nan", "NaT", "None"}:
        return []
    return [part.strip() for part in _SPLIT.split(text) if part.strip()]


def apply_key_params(original: str, defaults: Sequence[str], replacements: Sequence[str]) -> str:
    """Replace library defaults in the original text with the confirmed values.

    Always starts from `original` (the catalog 标准描述), never from a previously
    substituted string. Longer tokens are replaced first so a short param cannot
    eat part of a longer one.
    """
    text = original or ""
    sources = [str(item) for item in (defaults or []) if str(item)]
    values = [str(item) for item in (replacements or [])]
    if len(values) < len(sources):
        values = values + [""] * (len(sources) - len(values))
    missing = [src for src in sources if src not in text]
    if missing:
        raise KeyParamReplaceError(missing)
    pairs = sorted(zip(sources, values[: len(sources)]), key=lambda item: len(item[0]), reverse=True)
    out = text
    for src, dst in pairs:
        out = out.replace(src, dst)
    return out
