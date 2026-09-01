"""Ingest ApplicationData into ProjectState bilingual overview fields."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from application_parser.models import ApplicationData
from src.language_copy import english_from_application, has_chinese
from src.models.project_state import ProjectState


def _sides_from_candidates(primary: str, candidates: Sequence[str]) -> Tuple[str, str]:
    primary = (primary or "").strip()
    ordered = [c.strip() for c in candidates if c and str(c).strip()]
    if primary and primary not in ordered:
        ordered = [primary] + ordered
    cn_vals = [c for c in ordered if has_chinese(c)]
    en_vals = [c for c in ordered if c and not has_chinese(c)]
    cn = cn_vals[0] if cn_vals else primary
    explicit_en = en_vals[0] if en_vals else ""
    en = english_from_application(cn, explicit_en)
    return cn, en


def _column_sides(
    col_cn: Dict[str, str], col_en: Dict[str, str]
) -> Tuple[Dict[str, str], Dict[str, str]]:
    cn_out: Dict[str, str] = {}
    en_out: Dict[str, str] = {}
    keys = set(col_cn) | set(col_en)
    for key in keys:
        cn_val = (col_cn.get(key) or "").strip()
        en_val = (col_en.get(key) or "").strip()
        if cn_val:
            cn_out[key] = cn_val
        en = english_from_application(cn_val, en_val)
        if en:
            en_out[key] = en
    return cn_out, en_out


def _ingest_flat_sample_fields(
    data: ApplicationData,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    fields: Dict[str, str] = {}
    fields_en: Dict[str, str] = {}
    candidates_map = data.sample_info_candidates or {}
    for key, raw in (data.sample_info or {}).items():
        if raw is None or not str(raw).strip():
            continue
        primary = str(raw).strip()
        cands: List[str] = list(candidates_map.get(key) or [primary])
        cn, en = _sides_from_candidates(primary, cands)
        fields[key] = cn
        if en:
            fields_en[key] = en
    return fields, fields_en


def apply_application_data(state: ProjectState, data: ApplicationData) -> None:
    """Write CN/EN applicant, report-title, and sample fields; do not drop English."""
    state.applicant_name = (data.applicant_name_cn or data.applicant_name or "").strip()
    state.applicant_address = (
        data.applicant_address_cn or data.applicant_address or ""
    ).strip()
    state.applicant_name_en = english_from_application(
        state.applicant_name, data.applicant_name_en or ""
    )
    state.applicant_address_en = english_from_application(
        state.applicant_address, data.applicant_address_en or ""
    )

    state.report_title_name = (
        data.report_title_name_cn or data.report_title_name_en or ""
    ).strip()
    state.report_title_address = (
        data.report_title_address_cn or data.report_title_address_en or ""
    ).strip()
    state.report_title_name_en = english_from_application(
        state.report_title_name, data.report_title_name_en or ""
    )
    state.report_title_address_en = english_from_application(
        state.report_title_address, data.report_title_address_en or ""
    )

    cols_cn = list(data.sample_columns_cn or [])
    cols_en = list(data.sample_columns_en or [])
    if len(cols_cn) > 1:
        columns: List[Dict[str, str]] = []
        columns_en: List[Dict[str, str]] = []
        for i, col_cn in enumerate(cols_cn):
            col_en = cols_en[i] if i < len(cols_en) else {}
            cn_dict, en_dict = _column_sides(col_cn, col_en)
            columns.append(cn_dict)
            columns_en.append(en_dict)
        state.application_columns = columns
        state.application_columns_en = columns_en
        state.sample_column_tab_labels = list(data.sample_column_tab_labels or [])
        if len(state.sample_column_tab_labels) < len(columns):
            state.sample_column_tab_labels.extend(
                f"{j + 1:03d}"
                for j in range(len(state.sample_column_tab_labels), len(columns))
            )
        state.active_sample_column_index = 0
    elif len(cols_cn) == 1:
        cn_dict, en_dict = _column_sides(cols_cn[0], cols_en[0] if cols_en else {})
        if not cn_dict:
            cn_dict, en_dict = _ingest_flat_sample_fields(data)
        state.application_columns = [cn_dict] if cn_dict else []
        state.application_columns_en = [en_dict] if en_dict else []
        labels = list(data.sample_column_tab_labels or [])
        state.sample_column_tab_labels = labels[:1] if labels else (["001"] if cn_dict else [])
        state.active_sample_column_index = 0
    else:
        fields, fields_en = _ingest_flat_sample_fields(data)
        state.application_columns = [fields] if fields else []
        state.application_columns_en = [fields_en] if fields_en else []
        labels = list(data.sample_column_tab_labels or [])
        state.sample_column_tab_labels = labels[:1] if labels else (["001"] if fields else [])
        state.active_sample_column_index = 0

    state.sync_application_fields_from_sample_column()
    from src.io.special_rules import refresh_special_profile

    refresh_special_profile(state)
