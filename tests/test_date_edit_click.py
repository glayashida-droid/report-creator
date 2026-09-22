"""Clicks on a calendar date field must not step the current section."""

from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDateEdit, QStyle, QStyleOptionComboBox

from src.ui.theme import CYBERPUNK_QSS, polish_date_edit_calendar


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _arrow_rect(edit):
    opt = QStyleOptionComboBox()
    opt.initFrom(edit)
    opt.editable = True
    opt.subControls = QStyle.SubControl.SC_All
    return edit.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox,
        opt,
        QStyle.SubControl.SC_ComboBoxArrow,
        edit,
    )


def test_blank_area_beside_calendar_arrow_does_not_step():
    app = _app()
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy.MM.dd")
    edit.lineEdit().setReadOnly(True)
    edit.setStyleSheet(CYBERPUNK_QSS)
    polish_date_edit_calendar(edit)
    start = QDate(2040, 9, 4)
    edit.setDate(start)
    edit.resize(220, 32)
    edit.show()
    app.processEvents()

    line = edit.lineEdit().geometry()
    arrow = _arrow_rect(edit)
    assert arrow.isValid() and not arrow.isEmpty()

    changed = []
    width, height = edit.width(), edit.height()
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            point = QPoint(x, y)
            if line.contains(point):
                continue
            edit.setDate(start)
            QTest.mouseClick(edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            app.processEvents()
            if edit.date() != start:
                changed.append((x, y, edit.date().toString("yyyy.MM.dd")))
    edit.setDate(start)
    QTest.mousePress(
        edit, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, arrow.center()
    )
    app.processEvents()
    popup = next(
        (w for w in app.topLevelWidgets() if w.objectName() == "qt_datetimedit_calendar" and w.isVisible()),
        None,
    )
    popup_open = popup is not None and edit.date() == start
    if popup is not None:
        popup.close()
    edit.close()

    assert changed == []
    assert popup_open
