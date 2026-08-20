from datetime import datetime
import sys

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

from src.models.project_state import TestEquipment, TestNode
from src.ui.test_detail_dialog import (
    _EQ_EXPIRED_ROLE,
    _format_cal_date,
    _is_equipment_expired,
    _parse_qdate,
    TestDetailDialog,
    equipment_should_restore,
)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_parse_datetime_and_iso_string():
    assert _parse_qdate(datetime(2026, 11, 30, 0, 0)) == QDate(2026, 11, 30)
    assert _parse_qdate("2027-07-16 00:00:00") == QDate(2027, 7, 16)
    assert _parse_qdate("2026/9/17\n停用") == QDate(2026, 9, 17)


def test_parse_missing_or_note_is_invalid():
    assert not _parse_qdate(None).isValid()
    assert not _parse_qdate("").isValid()
    assert not _parse_qdate(float("nan")).isValid()
    assert not _parse_qdate("报废").isValid()
    assert not _parse_qdate("免校").isValid()


def test_format_prefers_iso_date():
    assert _format_cal_date(datetime(2026, 10, 8)) == "2026-10-08"
    assert _format_cal_date("2026/9/17\n停用") == "2026-09-17"
    assert _format_cal_date("报废") == "报废"
    assert _format_cal_date("") == ""


def test_expired_only_when_cal_before_test_end():
    end = QDate(2026, 8, 17)
    assert _is_equipment_expired(datetime(2026, 8, 16), end)
    assert not _is_equipment_expired(datetime(2026, 8, 17), end)
    assert not _is_equipment_expired(datetime(2026, 8, 18), end)
    assert not _is_equipment_expired("报废", end)
    assert not _is_equipment_expired(None, end)
    assert not _is_equipment_expired(datetime(2026, 8, 1), QDate())


def test_equipment_table_shows_cal_date_and_marks_expired():
    _app()
    node = TestNode(test_name="振动", start_date="2026-08-10", end_date="2026-08-17")
    equipments = [
        {
            "设备编号": "SHAED-A050",
            "设备名称": "电子万能试验机",
            "型号": "E43.104",
            "计划校准时间": datetime(2026, 8, 1),
        },
        {
            "设备编号": "SHAED-A051",
            "设备名称": "温湿度环境箱",
            "型号": "C7",
            "计划校准时间": datetime(2026, 12, 1),
        },
    ]
    dlg = TestDetailDialog(node, [], equipments)
    try:
        assert dlg.eq_table.columnCount() == 5
        assert dlg.eq_table.horizontalHeaderItem(4).text() == "校准有效期"
        assert dlg.eq_table.item(0, 4).text() == "2026-08-01"
        assert dlg.eq_table.item(1, 4).text() == "2026-12-01"
        assert dlg.eq_table.item(0, 2).data(_EQ_EXPIRED_ROLE) is True
        assert dlg.eq_table.item(1, 2).data(_EQ_EXPIRED_ROLE) is False
        dlg.date_start.setDate(QDate(2026, 6, 1))
        dlg.date_end.setDate(QDate(2026, 7, 1))
        assert dlg.eq_table.item(0, 2).data(_EQ_EXPIRED_ROLE) is False
    finally:
        dlg.close()


def test_header_clear_unchecks_multiselect():
    _app()
    node = TestNode(test_name="振动")
    standards = [
        {"标准号": "S1", "章节号": "1", "试验名称": "t1"},
        {"标准号": "S2", "章节号": "2", "试验名称": "t2"},
    ]
    equipments = [
        {"设备编号": "A", "设备名称": "n1", "型号": "m", "计划校准时间": ""},
        {"设备编号": "B", "设备名称": "n2", "型号": "m", "计划校准时间": ""},
    ]
    dlg = TestDetailDialog(node, standards, equipments)
    try:
        assert dlg._std_clear_btn.text() == "✕"
        assert dlg._eq_clear_btn.text() == "✕"
        dlg.eq_table.item(0, 0).setCheckState(Qt.Checked)
        dlg.eq_table.item(1, 0).setCheckState(Qt.Checked)
        dlg.std_table.item(0, 0).setCheckState(Qt.Checked)
        dlg._eq_clear_btn.click()
        assert dlg.eq_table.item(0, 0).checkState() == Qt.Unchecked
        assert dlg.eq_table.item(1, 0).checkState() == Qt.Unchecked
        dlg._std_clear_btn.click()
        assert dlg.std_table.item(0, 0).checkState() == Qt.Unchecked
        assert dlg._std_pick_order == []
    finally:
        dlg.close()


def test_restore_equipments_matches_code_not_shared_name():
    saved = [
        TestEquipment(code="SHAED-A050", name="电子万能试验机"),
        TestEquipment(code="SHAED-C001", name="温湿度环境箱"),
    ]
    assert equipment_should_restore("SHAED-A050", "电子万能试验机", saved)
    assert equipment_should_restore("SHAED-C001", "温湿度环境箱", saved)
    assert not equipment_should_restore("SHAED-A051", "电子万能试验机", saved)
    assert not equipment_should_restore("SHAED-C002", "温湿度环境箱", saved)

    _app()
    node = TestNode(test_name="冲击", equipments=saved)
    catalog = [
        {"设备编号": "SHAED-A050", "设备名称": "电子万能试验机", "型号": "x", "计划校准时间": ""},
        {"设备编号": "SHAED-A051", "设备名称": "电子万能试验机", "型号": "x", "计划校准时间": ""},
        {"设备编号": "SHAED-C001", "设备名称": "温湿度环境箱", "型号": "x", "计划校准时间": ""},
        {"设备编号": "SHAED-C002", "设备名称": "温湿度环境箱", "型号": "x", "计划校准时间": ""},
    ]
    dlg = TestDetailDialog(node, [], catalog)
    try:
        checked = [
            dlg.eq_table.item(row, 1).text()
            for row in range(dlg.eq_table.rowCount())
            if dlg.eq_table.item(row, 0).checkState() == Qt.Checked
        ]
        assert checked == ["SHAED-A050", "SHAED-C001"]
        assert dlg.drawer_eq.lbl_summary._full.startswith("已选 2 台")
        tip = dlg.drawer_eq.lbl_summary.toolTip()
        assert "SHAED-A050" in tip and "SHAED-C001" in tip
        assert "\n" in tip
        assert not hasattr(dlg, "lbl_eq_pick")
        assert not hasattr(dlg, "lbl_std_pick")
    finally:
        dlg.close()


def test_equipment_displays_tte_and_saves_valid_date():
    _app()
    node = TestNode(test_name="冲击")
    catalog = [
        {
            "设备编号": "SHAED-V066",
            "内部编号": "TTE20236127",
            "设备名称": "水平冲击试验台",
            "型号": "SY12-100A",
            "计划校准时间": datetime(2027, 1, 22),
        },
        {
            "设备编号": "SHAED-V067",
            "内部编号": "",
            "设备名称": "单轴加速度传感器",
            "型号": "BW23108",
            "计划校准时间": datetime(2027, 3, 9),
        },
    ]
    dlg = TestDetailDialog(node, [], catalog)
    try:
        assert dlg.eq_table.item(0, 1).text() == "TTE20236127-V066"
        assert dlg.eq_table.item(1, 1).text() == "SHAED-V067"
        dlg.eq_table.item(0, 0).setCheckState(Qt.Checked)
        picked = dlg._selected_equipments()
        assert len(picked) == 1
        assert picked[0].code == "TTE20236127-V066"
        assert picked[0].valid_date == "2027-01-22"
        # restore from saved TTE code still checks the catalog row
        node.equipments = picked
        dlg2 = TestDetailDialog(node, [], catalog)
        try:
            assert dlg2.eq_table.item(0, 0).checkState() == Qt.Checked
            assert dlg2.eq_table.item(1, 0).checkState() == Qt.Unchecked
        finally:
            dlg2.close()
    finally:
        dlg.close()


def test_legacy_equipment_name_matches_codes_not_names():
    legacy = "SHAED-A050 电子万能试验机；SHAED-C001 温湿度环境箱"
    assert equipment_should_restore("SHAED-A050", "电子万能试验机", [], legacy)
    assert not equipment_should_restore("SHAED-A051", "电子万能试验机", [], legacy)


if __name__ == "__main__":
    test_parse_datetime_and_iso_string()
    test_parse_missing_or_note_is_invalid()
    test_format_prefers_iso_date()
    test_expired_only_when_cal_before_test_end()
    test_equipment_table_shows_cal_date_and_marks_expired()
    test_header_clear_unchecks_multiselect()
    test_restore_equipments_matches_code_not_shared_name()
    test_equipment_displays_tte_and_saves_valid_date()
    test_legacy_equipment_name_matches_codes_not_names()
    print("ok")
