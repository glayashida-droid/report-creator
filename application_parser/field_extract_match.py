"""申请单与报告字段值的模糊匹配、日期等价、多样品列对齐（兼容入口）。

实现已按职责拆到：
- ``field_extract_quantity``：送样/检测数量
- ``field_extract_values``：空值/日期/值比对/叙述型结果表
- ``field_extract_sample_keys``：字段别名与 sample_info 查找
- ``field_extract_row_match``：多样品行列级匹配

外部请继续 ``from application_parser.field_extract_match import ...``。
"""
from __future__ import annotations

from application_parser.field_extract_quantity import (
    QUANTITY_UNIT_SUFFIX_ALT,
    is_quantity_sample_field,
    looks_like_sample_quantity_text,
    parse_compound_sample_quantity,
    quantity_candidates_total,
    quantity_values_match,
    try_parse_quantity_number,
)
from application_parser.field_extract_row_match import (
    _all_candidates_contained_in_report,
    match_application_row_value,
    report_compare_tokens,
    report_sample_value_has_merged_extra,
)
from application_parser.field_extract_sample_keys import (
    SAMPLE_COMPARE_SKIP,
    SAMPLE_FIELD_ALIASES,
    _sample_field_key_compatible,
    ensure_quantity_in_sample_info,
    find_sample_entry,
    find_sample_value,
    format_application_row_reference,
    sample_field_alias_keys,
    sample_fields_equivalent_for_lookup,
    sample_storage_keys_alias_equivalent,
    should_compare_sample_field,
)
from application_parser.field_extract_values import (
    calendar_dates_equal,
    count_narrative_result_rows,
    format_sample_field_display,
    is_blank_or_slash,
    is_generic_material_value,
    is_narrative_results_table,
    is_placeholder_application_number,
    match_application_number,
    normalize_compare_value,
    oem_values_match,
    try_parse_calendar_date,
    values_match,
)

__all__ = [
    "QUANTITY_UNIT_SUFFIX_ALT",
    "SAMPLE_COMPARE_SKIP",
    "SAMPLE_FIELD_ALIASES",
    "_all_candidates_contained_in_report",
    "_sample_field_key_compatible",
    "calendar_dates_equal",
    "count_narrative_result_rows",
    "ensure_quantity_in_sample_info",
    "find_sample_entry",
    "find_sample_value",
    "format_application_row_reference",
    "format_sample_field_display",
    "is_blank_or_slash",
    "is_generic_material_value",
    "is_narrative_results_table",
    "is_placeholder_application_number",
    "is_quantity_sample_field",
    "looks_like_sample_quantity_text",
    "match_application_number",
    "match_application_row_value",
    "normalize_compare_value",
    "oem_values_match",
    "parse_compound_sample_quantity",
    "quantity_candidates_total",
    "quantity_values_match",
    "report_compare_tokens",
    "report_sample_value_has_merged_extra",
    "sample_field_alias_keys",
    "sample_fields_equivalent_for_lookup",
    "sample_storage_keys_alias_equivalent",
    "should_compare_sample_field",
    "try_parse_calendar_date",
    "try_parse_quantity_number",
    "values_match",
]
