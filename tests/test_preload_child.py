"""Catalog and board preloads run in a child process."""

from datetime import date

from openpyxl import Workbook

from src.io.preload_child import isolated_list_board_rows, isolated_load_catalogs
from src.parsers.db_loader import DUPLICATE_STANDARD_MSG, BaseDataLoader


def _workbook(path, headers, rows):
    book = Workbook()
    sheet = book.active
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    book.save(path)


def test_isolated_catalogs_round_trip_into_the_loader(tmp_path):
    standards = tmp_path / "标准库.xlsx"
    equipment = tmp_path / "设备清单.xlsx"
    _workbook(standards, ["标准号", "章节号", "试验名称"], [["ABC", "1.1", "振动"]])
    _workbook(equipment, ["设备编号", "设备名称"], [["E1", "示波器"]])

    payload = isolated_load_catalogs(str(standards), str(equipment))
    assert payload["standards_error"] == ""
    assert payload["equipments_error"] == ""
    assert payload["standards_frame"].iloc[0]["标准号"] == "ABC"
    assert payload["equipments_frame"].iloc[0]["设备名称"] == "示波器"

    loader = BaseDataLoader(network_mode=True)
    loader.install_standards(
        payload["standards_frame"],
        payload["standard_images"],
        payload["standards_mtime"],
    )
    loader.install_equipments(payload["equipments_frame"], payload["equipments_mtime"])
    peeked = loader.peek_standards()
    assert peeked[0]["标准号"] == "ABC"
    assert peeked[0]["试验名称"] == "振动"
    assert loader.peek_equipments()[0]["设备编号"] == "E1"


def test_isolated_catalogs_report_duplicate_standards(tmp_path):
    standards = tmp_path / "标准库.xlsx"
    _workbook(
        standards,
        ["标准号", "章节号", "试验名称"],
        [["ABC", "1.1", "振动"], ["ABC", "1.1", "振动再次"]],
    )
    payload = isolated_load_catalogs(str(standards), None)
    assert DUPLICATE_STANDARD_MSG in payload["standards_error"]
    assert payload["standards_records"] is None
    assert payload["equipments_records"] is None


def test_isolated_board_scan_of_an_empty_folder(tmp_path):
    rows = isolated_list_board_rows(tmp_path, today=date(2026, 1, 1))
    assert rows == []
