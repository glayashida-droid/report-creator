"""Keep nested scrollable widgets from chaining wheel events to parents.

When an inner QTableWidget / QTextEdit / QScrollArea hits its scroll limit,
Qt ignores the wheel event and the outer dialog QScrollArea starts moving.
These subclasses always accept the wheel so the outer form stays put until
the cursor leaves the inner widget.
"""

from PySide6.QtWidgets import QScrollArea, QTableWidget, QTextEdit


class ContainedTableWidget(QTableWidget):
    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()


class ContainedTextEdit(QTextEdit):
    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()


class ContainedScrollArea(QScrollArea):
    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()
