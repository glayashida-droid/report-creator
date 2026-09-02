import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.generators.word_engine import WordGenerator
from src.models.project_state import TestNode
from src.ui.test_detail_dialog import TestDetailDialog


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _catalog():
    return [
        {
            "标准号": "VW82511-2010",
            "章节号": "8.3.6",
            "试验名称": "盐雾试验",
            "标准描述": "条件",
            "结果描述": "描述",
            "评价要求": "要求",
        }
    ]


def test_method_field_is_editable_and_autofills_on_select():
    _app()
    dlg = TestDetailDialog(TestNode(test_name="盐雾"), _catalog(), [])
    try:
        assert dlg.txt_std_method.isReadOnly() is False
        assert dlg.txt_std_method.text() == ""
        dlg.std_table.item(0, 0).setCheckState(Qt.Checked)
        assert dlg.txt_std_method.text() == "VW82511-2010 / 8.3.6"
        dlg.txt_std_method.setText("VW82511-2010 / 8.3.6 盐雾")
        assert dlg.txt_std_method.text() == "VW82511-2010 / 8.3.6 盐雾"
    finally:
        dlg.close()


def test_edited_method_saves_and_reloads():
    _app()
    node = TestNode(test_name="盐雾")
    dlg = TestDetailDialog(node, _catalog(), [])
    try:
        dlg.std_table.item(0, 0).setCheckState(Qt.Checked)
        dlg.txt_std_method.setText("自定义检测方法")
        dlg.save_and_close()
    finally:
        dlg.close()

    assert node.test_method == "自定义检测方法"

    dlg2 = TestDetailDialog(node, _catalog(), [])
    try:
        assert dlg2.txt_std_method.isReadOnly() is False
        assert dlg2.txt_std_method.text() == "自定义检测方法"
    finally:
        dlg2.close()


def test_word_engine_uses_edited_method():
    node = TestNode(
        test_name="盐雾",
        test_method="VW82511-2010 / 8.3.6 盐雾",
        standard_id="VW82511-2010",
        standard_chapter="8.3.6",
    )
    assert WordGenerator._format_method(node) == "VW82511-2010 / 8.3.6 盐雾"


def test_word_engine_keeps_hyphen_when_method_not_edited():
    node = TestNode(
        test_name="盐雾",
        standard_id="VW82511-2010",
        standard_chapter="8.3.6",
    )
    assert WordGenerator._format_method(node) == "VW82511-2010-8.3.6"
