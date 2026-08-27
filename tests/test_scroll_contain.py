"""Nested scroll containment: wheel events stay on inner widgets."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QTableWidgetItem, QWidget, QVBoxLayout

from src.ui.scroll_contain import (
    ContainedScrollArea,
    ContainedTableWidget,
    ContainedTextEdit,
)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _wheel(widget, delta=-120):
    pos = widget.rect().center()
    global_pos = widget.mapToGlobal(pos)
    return QWheelEvent(
        pos,
        global_pos,
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )


def test_contained_table_accepts_wheel_at_boundary():
    _app()
    outer = QScrollArea()
    host = QWidget()
    layout = QVBoxLayout(host)
    table = ContainedTableWidget(20, 1)
    table.setFixedHeight(80)
    for row in range(20):
        table.setItem(row, 0, QTableWidgetItem(f"r{row}"))
    layout.addWidget(table)
    layout.addWidget(QWidget())
    outer.setWidget(host)
    outer.setWidgetResizable(True)
    outer.resize(300, 120)
    outer.show()
    _app().processEvents()

    bar = table.verticalScrollBar()
    bar.setValue(bar.maximum())
    event = _wheel(table)
    table.wheelEvent(event)
    assert event.isAccepted()


def test_contained_text_edit_accepts_wheel():
    _app()
    edit = ContainedTextEdit()
    edit.setPlainText("\n".join(f"line {i}" for i in range(40)))
    edit.setFixedHeight(60)
    edit.show()
    _app().processEvents()
    bar = edit.verticalScrollBar()
    bar.setValue(bar.maximum())
    event = _wheel(edit)
    edit.wheelEvent(event)
    assert event.isAccepted()


def test_contained_scroll_area_accepts_wheel():
    _app()
    area = ContainedScrollArea()
    inner = QWidget()
    inner.setMinimumHeight(400)
    area.setWidget(inner)
    area.setWidgetResizable(True)
    area.setFixedHeight(80)
    area.show()
    _app().processEvents()
    bar = area.verticalScrollBar()
    bar.setValue(bar.maximum())
    event = _wheel(area)
    area.wheelEvent(event)
    assert event.isAccepted()


def test_plain_table_ignores_wheel_at_boundary():
    """Baseline: stock QTableWidget leaves wheel ignored at the limit."""
    from PySide6.QtWidgets import QTableWidget

    _app()
    table = QTableWidget(20, 1)
    table.setFixedHeight(80)
    for row in range(20):
        table.setItem(row, 0, QTableWidgetItem(f"r{row}"))
    table.show()
    _app().processEvents()
    bar = table.verticalScrollBar()
    bar.setValue(bar.maximum())
    event = _wheel(table)
    table.wheelEvent(event)
    assert not event.isAccepted()
