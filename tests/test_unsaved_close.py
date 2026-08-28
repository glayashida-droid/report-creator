import sys

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_date_change_without_project_is_not_dirty():
    _app()
    win = MainWindow()
    assert not win.state.project_id
    win.date_receive.setDate(QDate(2026, 8, 12))
    QApplication.processEvents()
    assert not win._is_dirty
    assert not win._has_unsaved_changes()
    assert win._confirm_discard_if_dirty() is True


def test_date_change_with_project_marks_dirty():
    _app()
    win = MainWindow()
    win.state.project_id = "A22600000001"
    win.date_receive.setDate(QDate(2026, 8, 12))
    QApplication.processEvents()
    assert win._is_dirty
    assert win._has_unsaved_changes()


def test_mark_dirty_ignored_without_project():
    _app()
    win = MainWindow()
    win._mark_dirty()
    assert not win._is_dirty
    assert not win._has_unsaved_changes()


if __name__ == "__main__":
    test_date_change_without_project_is_not_dirty()
    test_date_change_with_project_marks_dirty()
    test_mark_dirty_ignored_without_project()
    print("test_unsaved_close: ok")
