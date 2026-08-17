from __future__ import annotations

import os
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd

from src.models.project_state import TestLeg, TestStandard
from src.parsers.key_params import parse_key_params
from src.parsers.xlsx_images import load_xlsx_row_images

DUPLICATE_STANDARD_MSG = "标准库中存在相同章节内容，请确认"


class DuplicateStandardError(ValueError):
    def __init__(self, duplicates: Sequence[Tuple[str, str]] | None = None):
        super().__init__(DUPLICATE_STANDARD_MSG)
        self.duplicates = list(duplicates or [])


def cell_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text in {"", "nan", "NaT", "None"}:
        return ""
    return text


def standard_ref_key(std_no, chapter) -> Tuple[str, str]:
    return (cell_text(std_no), cell_text(chapter))


def record_ref_key(record: Dict[str, Any] | None) -> Tuple[str, str]:
    rec = record or {}
    return standard_ref_key(rec.get("标准号"), rec.get("章节号"))


def find_duplicate_standard_refs(records: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    seen = set()
    duplicates = []
    for rec in records:
        key = record_ref_key(rec)
        if not key[0] or not key[1]:
            continue
        if key in seen:
            if key not in duplicates:
                duplicates.append(key)
        else:
            seen.add(key)
    return duplicates


def duplicate_standard_message(exc: DuplicateStandardError) -> str:
    lines = [str(exc)]
    for std_no, chapter in exc.duplicates:
        lines.append(f"{std_no} / {chapter}")
    return "\n".join(lines)


def catalog_by_ref(records: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rec in records:
        key = record_ref_key(rec)
        if not key[0] and not key[1]:
            continue
        out[key] = rec
    return out


def hydrate_standard_from_record(std: TestStandard, record: Dict[str, Any]) -> TestStandard:
    defaults = parse_key_params(record.get("关键参数"))
    return TestStandard(
        standard_id=cell_text(record.get("标准号")) or std.standard_id,
        chapter=cell_text(record.get("章节号")) or std.chapter,
        test_name=cell_text(record.get("试验名称")) or std.test_name,
        standard_desc=cell_text(record.get("标准描述")),
        result_desc=cell_text(record.get("结果描述")),
        evaluation_req=cell_text(record.get("评价要求")),
        images=list(record.get("_images") or []),
        key_params=list(defaults),
        key_params_defaults=list(defaults),
        key_params_confirmed=False,
    )


def hydrate_legs_from_catalog(legs: Sequence[TestLeg], catalog: Sequence[Dict[str, Any]]) -> None:
    """Fill conditions / images / eval / result from the live library. Card names stay put."""
    by_ref = catalog_by_ref(catalog)
    for leg in legs or []:
        for node in leg.nodes or []:
            picked = []
            for std in node.resolved_standards():
                rec = by_ref.get(std.ref_key())
                if rec:
                    picked.append(hydrate_standard_from_record(std, rec))
                else:
                    picked.append(
                        TestStandard(
                            standard_id=std.standard_id,
                            chapter=std.chapter,
                            test_name=std.test_name,
                        )
                    )
            node.apply_standards(picked)


class BaseDataLoader:
    def __init__(self, db_folder: str = "database"):
        self.db_folder = db_folder
        self.standards_df = None
        self.equipments_df = None
        self._standard_images = None
        self._standards_mtime = None

    def load_standards(self) -> List[Dict[str, Any]]:
        path = f"{self.db_folder}/标准库.xlsx"
        mtime = os.path.getmtime(path)
        if self.standards_df is None or mtime != self._standards_mtime:
            df = pd.read_excel(path)
            df = df.fillna("")
            records = df.to_dict("records")
            duplicates = find_duplicate_standard_refs(records)
            if duplicates:
                raise DuplicateStandardError(duplicates)
            self.standards_df = df
            self._standard_images = load_xlsx_row_images(path)
            self._standards_mtime = mtime

        records = self.standards_df.to_dict("records")
        images = self._standard_images or {}
        for index, rec in enumerate(records):
            rec["_images"] = list(images.get(index + 2, []))
        return records

    def load_equipments(self) -> List[Dict[str, Any]]:
        if self.equipments_df is None:
            path = f"{self.db_folder}/01-设备清单.xlsx"
            self.equipments_df = pd.read_excel(path)  # Removed skiprows=1 because columns are on the first row
            self.equipments_df = self.equipments_df.fillna("")

        return self.equipments_df.to_dict("records")
