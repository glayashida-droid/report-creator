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


class ImportTemplateDialog(QDialog):
    def __init__(self, templates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入 Leg 模板")
        self.resize(560, 340)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择要导入的 Leg 模板:"))

        self.list_w = QListWidget()
        for template in templates:
            stamp = datetime.fromtimestamp(template.saved_at).strftime("%Y-%m-%d %H:%M")
            label = (
                f"{template.name}    "
                f"{template.leg_count} Leg / {template.test_count} 试验    "
                f"{stamp}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, template)
            self.list_w.addItem(item)
        if self.list_w.count():
            self.list_w.setCurrentRow(0)
        self.list_w.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_w)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_template(self):
        item = self.list_w.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)
