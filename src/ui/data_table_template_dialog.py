from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QAbstractItemView,
)


class CheckRowListWidget(QListWidget):
    """Whole-row click toggles the checkbox once (no Qt double-toggle)."""

    def mousePressEvent(self, event):
        # Swallow press on rows so Qt's ItemIsUserCheckable path never runs.
        if (
            event.button() == Qt.LeftButton
            and self.itemAt(event.position().toPoint()) is not None
        ):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.button() == Qt.LeftButton:
            item.setCheckState(
                Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
            )
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DataTableTemplateDialog(QDialog):
    """Pick one or more data-table templates via checkboxes; filter by name."""

    def __init__(self, templates: list[Path], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择数据表模版")
        self.resize(480, 400)
        self._templates = list(templates)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("勾选需要的模版（将分别复制为数据表）："))

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索模版名…")
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.list_w = CheckRowListWidget()
        self.list_w.setSelectionMode(QAbstractItemView.NoSelection)
        for path in self._templates:
            item = QListWidgetItem(path.name)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, path)
            self.list_w.addItem(item)
        layout.addWidget(self.list_w)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_filter(self, text: str):
        needle = (text or "").strip().lower()
        for i in range(self.list_w.count()):
            item = self.list_w.item(i)
            name = item.text().lower()
            item.setHidden(bool(needle) and needle not in name)

    def selected_paths(self) -> list[Path]:
        paths: list[Path] = []
        for i in range(self.list_w.count()):
            item = self.list_w.item(i)
            if item.isHidden():
                continue
            if item.checkState() != Qt.Checked:
                continue
            path = item.data(Qt.UserRole)
            if path is not None:
                paths.append(path)
        return paths
