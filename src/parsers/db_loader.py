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


def equipment_display_code(row: Dict[str, Any] | None) -> str:
    """Report/UI equipment number: 内部编号-后缀 (TTE…), fallback to 设备编号."""
    rec = row or {}
    raw = cell_text(rec.get("设备编号"))
    internal = cell_text(rec.get("内部编号"))
    if not internal:
        return raw
    if raw.upper().startswith("SHAED-") and "-" in raw:
        suffix = raw.split("-", 1)[-1]
        if suffix:
            return f"{internal}-{suffix}"
    return internal


def equipment_match_codes(row: Dict[str, Any] | None) -> List[str]:
    """All code forms that should match a catalog row when restoring picks."""
    rec = row or {}
    codes = []
    for value in (
        cell_text(rec.get("设备编号")),
        cell_text(rec.get("内部编号")),
        equipment_display_code(rec),
    ):
        if value and value not in codes:
            codes.append(value)
    return codes


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
        test_item=cell_text(record.get("test item")),
        standard_desc=cell_text(record.get("标准描述")),
        standard_desc_en=cell_text(record.get("condition")),
        result_desc=cell_text(record.get("结果描述")),
        result_desc_en=cell_text(record.get("result")),
        evaluation_req=cell_text(record.get("评价要求")),
        evaluation_req_en=cell_text(record.get("Evaluation requirement")),
        env_condition=cell_text(record.get("环境温湿度")),
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
    def __init__(
        self,
        db_folder: str = "database",
        *,
        network_mode: bool = False,
        standards_path: str | None = None,
        equipment_path: str | None = None,
    ):
        self.db_folder = db_folder
        self.network_mode = network_mode
        self.standards_df = None
        self.equipments_df = None
        self._standard_images = None
        self._standards_mtime = None
        self._equipments_mtime = None
        self._standards_path = standards_path
        self._equipment_path = equipment_path
        self.standards_connected = False
        self.equipment_connected = False
        if not network_mode:
            self._standards_path = standards_path or os.path.join(db_folder, "标准库.xlsx")
            self._equipment_path = equipment_path or os.path.join(
                db_folder, "01-设备清单.xlsx"
            )
            self.standards_connected = os.path.isfile(self._standards_path)
            self.equipment_connected = os.path.isfile(self._equipment_path)

    @property
    def is_standards_ready(self) -> bool:
        if self.network_mode:
            return self.standards_connected
        return bool(self._standards_path and os.path.isfile(self._standards_path))

    @property
    def is_equipment_ready(self) -> bool:
        if self.network_mode:
            return self.equipment_connected
        return bool(self._equipment_path and os.path.isfile(self._equipment_path))

    def apply_network_probe(
        self,
        *,
        standards_path: str | None,
        standards_ok: bool,
        equipment_path: str | None,
        equipment_ok: bool,
    ) -> None:
        if standards_path != self._standards_path:
            self.standards_df = None
            self._standard_images = None
            self._standards_mtime = None
        if equipment_path != self._equipment_path:
            self.equipments_df = None
            self._equipments_mtime = None
        self._standards_path = standards_path
        self._equipment_path = equipment_path
        self.standards_connected = bool(standards_ok and standards_path)
        self.equipment_connected = bool(equipment_ok and equipment_path)

    def load_standards(self) -> List[Dict[str, Any]]:
        if not self.is_standards_ready or not self._standards_path:
            raise FileNotFoundError("标准库尚未就绪")
        path = self._standards_path
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
        if not self.is_equipment_ready or not self._equipment_path:
            raise FileNotFoundError("设备清单尚未就绪")
        path = self._equipment_path
        mtime = os.path.getmtime(path)
        if self.equipments_df is None or mtime != self._equipments_mtime:
            self.equipments_df = pd.read_excel(path)
            self.equipments_df = self.equipments_df.fillna("")
            self._equipments_mtime = mtime

        return self.equipments_df.to_dict("records")
