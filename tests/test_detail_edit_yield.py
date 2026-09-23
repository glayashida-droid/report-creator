"""Detail editing: catalogs fill once on open, result text copies on pause."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.models.project_state import TestNode
from src.ui.test_detail_dialog import TestDetailDialog


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _standards(count):
    return [
        {
            "标准号": f"S{index}",
            "章节号": "1",
            "试验名称": f"试验{index}",
            "结果描述": "描述甲",
        }
        for index in range(count)
    ]


def test_standards_table_fills_in_one_pass():
    _app()
    dlg = TestDetailDialog(TestNode(test_name="振动"), _standards(13), [])
    try:
        assert dlg.drawer_std.lbl_summary.text() == "未选择"
        dlg._ensure_standards_table()
        assert dlg._std_table_ready
        assert dlg._std_table.isEnabled()
        assert dlg._std_table.item(12, 1).text() == "S12"
        assert dlg.drawer_std.lbl_summary.text() == "未选择"
    finally:
        dlg.close()


def test_checking_equipment_keeps_the_other_rows():
    _app()
    equipments = [
        {
            "设备编号": f"E{index}",
            "设备名称": f"设备{index}",
            "型号": "M",
            "校准时间": "2026-01-01",
        }
        for index in (1, 2, 3)
    ]
    dlg = TestDetailDialog(TestNode(test_name="振动"), [], equipments)
    try:
        dlg._ensure_equipment_table()
        dlg.eq_table.item(0, 0).setCheckState(Qt.Checked)
        dlg.eq_table.item(2, 0).setCheckState(Qt.Checked)
        assert [item.code for item in dlg._selected_equipments()] == ["E1", "E3"]
        dlg.eq_table.item(0, 0).setCheckState(Qt.Unchecked)
        assert [item.code for item in dlg._selected_equipments()] == ["E3"]
    finally:
        dlg.close()


def test_result_desc_reaches_sample_rows_when_editing_pauses():
    _app()
    dlg = TestDetailDialog(TestNode(test_name="振动"), _standards(1), [])
    try:
        dlg.std_table.item(0, 0).setCheckState(Qt.Checked)
        dlg.add_sample_row("A01")
        editor = dlg.result_desc_table.cellWidget(0, 1)
        sample = dlg.table.cellWidget(0, 2)
        assert sample.text() == "描述甲"
        editor.setPlainText("新描述")
        QApplication.processEvents()
        assert sample.text() == "描述甲"
        dlg._flush_result_desc_now()
        assert sample.text() == "新描述"
    finally:
        dlg.close()


def test_catalog_arrival_keeps_fields_the_user_already_edited():
    _app()
    dlg = TestDetailDialog(
        TestNode(test_name="振动"), [], [], catalogs_pending=True
    )
    try:
        dlg.txt_env_condition.setText("用户改的环境")
        dlg.txt_env_condition.setModified(True)
        dlg.txt_std_method.setText("用户改的方法")
        dlg.txt_std_method.setModified(True)
        dlg.apply_catalogs(
            [
                {
                    "标准号": "ABC",
                    "章节号": "1.1",
                    "试验名称": "振动",
                    "环境温湿度": "23℃",
                }
            ],
            [],
            "",
        )
        assert dlg.txt_env_condition.text() == "用户改的环境"
        assert dlg.txt_std_method.text() == "用户改的方法"
    finally:
        dlg.close()
