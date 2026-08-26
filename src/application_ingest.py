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

    state.application_fields = fields
    state.application_fields_en = fields_en
    state.sample_name = fields.get("样品名称", "") or state.sample_name
    state.sample_name_en = fields_en.get("样品名称", "") or english_from_application(
        state.sample_name, ""
    )
