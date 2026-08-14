from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class LoadStateDialog(QDialog):
    def __init__(self, projects, parent=None):
        super().__init__(parent)
        self.setWindowTitle("加载状态")
        self.resize(560, 340)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择要加载的项目:"))

        self.list_w = QListWidget()
        for project in projects:
            extra = "  ".join(
                part for part in (project.applicant_name, project.sample_name) if part
            )
            stamp = datetime.fromtimestamp(project.saved_at).strftime("%Y-%m-%d %H:%M")
            bits = [project.project_id]
            if extra:
                bits.append(extra)
            bits.append(stamp)
            item = QListWidgetItem("    ".join(bits))
            item.setData(Qt.UserRole, project)
            self.list_w.addItem(item)
        if self.list_w.count():
            self.list_w.setCurrentRow(0)
        self.list_w.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_w)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_project(self):
        item = self.list_w.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)
