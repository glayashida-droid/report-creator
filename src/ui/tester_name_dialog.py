"""Prompt for the tester name on startup / project load."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class TesterNameDialog(QDialog):
    def __init__(self, default_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("测试员")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        greeting = QLabel("😊 请填入姓名")
        greeting.setObjectName("dialogGreeting")
        layout.addWidget(greeting)

        label = QLabel("测试员：")
        layout.addWidget(label)

        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("请输入姓名")
        self.txt_name.setText((default_name or "").strip())
        layout.addWidget(self.txt_name)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def tester_name(self) -> str:
        return (self.txt_name.text() or "").strip()
