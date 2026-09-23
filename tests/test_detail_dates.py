import sys

from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from src.models.project_state import TestNode
from src.ui.test_detail_dialog import TestDetailDialog, _is_blank_node_date
from src.ui.theme import apply_cyberpunk_theme


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        apply_cyberpunk_theme(app)
    return app


def test_blank_dates_stay_blank_on_open():
    _app()
    dlg = TestDetailDialog(TestNode(test_name="高温"), [], [])
    assert _is_blank_node_date(dlg.date_start.date())
    assert _is_blank_node_date(dlg.date_end.date())
    assert dlg._apply_schedule_dates() is True
    assert dlg.node_data.start_date is None
    assert dlg.node_data.end_date is None
    dlg.close()


def test_existing_dates_load_and_can_clear():
    _app()
    node = TestNode(test_name="高温", start_date="2026-09-03", end_date="2026-09-05")
    dlg = TestDetailDialog(node, [], [])
    assert dlg.date_start.date() == QDate(2026, 9, 3)
    assert dlg.date_end.date() == QDate(2026, 9, 5)
    dlg._clear_node_date(dlg.date_start)
    dlg._clear_node_date(dlg.date_end)
    assert _is_blank_node_date(dlg.date_start.date())
    assert _is_blank_node_date(dlg.date_end.date())
    assert dlg._apply_schedule_dates() is True
    assert dlg.node_data.start_date is None
    assert dlg.node_data.end_date is None
    dlg.close()


def test_backspace_clears_date():
    _app()
    node = TestNode(test_name="高温", start_date="2026-09-03", end_date="2026-09-05")
    dlg = TestDetailDialog(node, [], [])
    dlg.show()
    QApplication.processEvents()
    line = dlg.date_start.lineEdit()
    line.setFocus()
    QTest.keyClick(line, Qt.Key_Backspace)
    QApplication.processEvents()
    assert _is_blank_node_date(dlg.date_start.date())
    assert dlg.date_end.date() == QDate(2026, 9, 5)
    dlg.close()


def test_one_blank_date_saves():
    _app()
    node = TestNode(test_name="高温", start_date="2026-09-03", end_date="2026-09-05")
    dlg = TestDetailDialog(node, [], [])
    dlg._clear_node_date(dlg.date_end)
    assert dlg._apply_schedule_dates() is True
    assert dlg.node_data.start_date == "2026-09-03"
    assert dlg.node_data.end_date is None
    dlg.close()


def test_enter_does_not_click_save_cancel_or_print():
    _app()
    dlg = TestDetailDialog(TestNode(test_name="高温"), [], [])
    dlg.show()
    QApplication.processEvents()
    hits = []
    for btn in dlg.findChildren(QPushButton):
        if btn.text() in ("保存", "取消", "打印TR"):
            btn.clicked.connect(lambda _checked=False, name=btn.text(): hits.append(name))
            assert btn.autoDefault() is False
            assert btn.isDefault() is False
    dlg.txt_env_condition.setFocus()
    QTest.keyClick(dlg.txt_env_condition, Qt.Key_Return)
    QTest.keyClick(dlg.txt_env_condition, Qt.Key_Enter)
    for btn in dlg.findChildren(QPushButton):
        if btn.text() in ("保存", "取消", "打印TR"):
            btn.setFocus()
            QTest.keyClick(btn, Qt.Key_Return)
    QApplication.processEvents()
    assert hits == []
    assert dlg.isVisible()
    dlg.close()


def test_top_bar_controls_match_env_height():
    _app()
    dlg = TestDetailDialog(TestNode(test_name="高温"), [], [])
    dlg.show()
    QApplication.processEvents()
    env_h = dlg.txt_env_condition.height()
    assert dlg.date_start.height() == env_h
    assert dlg.date_end.height() == env_h
    assert dlg.btn_print_raw.height() == env_h
    dlg.close()
