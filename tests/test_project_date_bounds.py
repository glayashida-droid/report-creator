import sys

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow, _is_blank_project_date


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _set_real_date(date_edit, year, month, day):
    date_edit.setDate(QDate(year, month, day))


def test_start_floor_is_receive_only():
    _app()
    win = MainWindow()
    _set_real_date(win.date_receive, 2026, 8, 12)
    _set_real_date(win.date_start, 2026, 8, 12)
    _set_real_date(win.date_end, 2026, 8, 20)
    QApplication.processEvents()

    cal = win.date_start.calendarWidget()
    assert cal.minimumDate() == QDate(2026, 8, 12)
    # Start is not capped by end — only floored by receive.
    assert cal.maximumDate() == QDate(9999, 12, 31)


def test_end_floor_is_start():
    _app()
    win = MainWindow()
    _set_real_date(win.date_receive, 2026, 8, 1)
    _set_real_date(win.date_start, 2026, 8, 12)
    _set_real_date(win.date_end, 2026, 8, 20)
    QApplication.processEvents()

    cal = win.date_end.calendarWidget()
    assert cal.minimumDate() == QDate(2026, 8, 12)


def test_receive_later_does_not_cascade():
    _app()
    win = MainWindow()
    _set_real_date(win.date_receive, 2026, 8, 1)
    _set_real_date(win.date_start, 2026, 8, 5)
    _set_real_date(win.date_end, 2026, 8, 10)
    QApplication.processEvents()

    _set_real_date(win.date_receive, 2026, 8, 12)
    QApplication.processEvents()
    assert win.date_start.date() == QDate(2026, 8, 5)
    assert win.date_end.date() == QDate(2026, 8, 10)
    assert not win._project_dates_in_order()


def test_blank_fields_stay_blank_when_bounds_refresh():
    _app()
    win = MainWindow()
    assert _is_blank_project_date(win.date_start.date())
    assert _is_blank_project_date(win.date_end.date())
    _set_real_date(win.date_receive, 2026, 8, 1)
    QApplication.processEvents()
    assert _is_blank_project_date(win.date_start.date())
    assert _is_blank_project_date(win.date_end.date())
    assert win.date_start.calendarWidget().minimumDate() == QDate(2026, 8, 1)
    assert win.date_end.calendarWidget().minimumDate() == QDate(2026, 8, 1)


def test_export_order_check_allows_same_day():
    _app()
    win = MainWindow()
    _set_real_date(win.date_receive, 2026, 8, 12)
    _set_real_date(win.date_start, 2026, 8, 12)
    _set_real_date(win.date_end, 2026, 8, 12)
    QApplication.processEvents()
    assert win._project_dates_in_order()


if __name__ == "__main__":
    test_blank_fields_stay_blank_when_bounds_refresh()
    test_start_floor_is_receive_only()
    test_end_floor_is_start()
    test_receive_later_does_not_cascade()
    test_export_order_check_allows_same_day()
    print("test_project_date_bounds: ok")
