"""Multi-column 申请单样品页：按列切换与 All 合并导出。"""

from __future__ import annotations

from typing import Dict, List, Sequence

from application_parser.field_extract import is_blank_or_slash, is_quantity_sample_field, values_match
from application_parser.field_extract_quantity import quantity_candidates_total

ALL_SAMPLE_COLUMNS = -1


def merge_column_field_values(values: Sequence[str], *, field_key: str = "") -> str:
    """Merge values from each sample column; dedupe equal values, join with ``/``."""
    active: List[str] = []
    for raw in values:
        val = (raw or "").strip()
        if is_blank_or_slash(val):
            continue
        if any(values_match(val, existing) for existing in active):
            continue
        active.append(val)
    if not active:
        return ""
    if is_quantity_sample_field(field_key) and len(active) > 1:
        total = quantity_candidates_total(list(active))
        if total is not None:
            return str(total)
    if len(active) == 1:
        return active[0]
    return "/".join(active)


def merge_sample_column_dicts(
    columns: List[Dict[str, str]],
    *,
    field_keys: Sequence[str] | None = None,
) -> Dict[str, str]:
    if not columns:
        return {}
    keys = list(field_keys) if field_keys is not None else []
    if not keys:
        seen = set()
        for col in columns:
            for key in col:
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
    merged: Dict[str, str] = {}
    for key in keys:
        text = merge_column_field_values([col.get(key, "") for col in columns], field_key=key)
        if text:
            merged[key] = text
    return merged


def build_sample_column_tab_labels(
    *,
    num_columns: int,
    sample_seq: Sequence[str],
    sample_names: Sequence[str],
) -> List[str]:
    labels: List[str] = []
    for i in range(num_columns):
        seq = (sample_seq[i] if i < len(sample_seq) else "").strip()
        if seq and not is_blank_or_slash(seq):
            labels.append(seq)
            continue
        name = (sample_names[i] if i < len(sample_names) else "").strip()
        if name and not is_blank_or_slash(name):
            labels.append(name[:24] + ("…" if len(name) > 24 else ""))
            continue
        labels.append(f"{i + 1:03d}")
    return labels
