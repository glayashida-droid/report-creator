from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class SaveSuccessDialog(QDialog):
    """Brief confirmation after saving project details; auto-closes after a countdown."""

    def __init__(self, parent=None, *, seconds: int = 3):
        super().__init__(parent)
        self.setWindowTitle("提示")
        self.setModal(True)
        self._remaining = seconds

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        message = QLabel("项目已保存")
        message.setAlignment(Qt.AlignCenter)
        root.addWidget(message)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setObjectName("accentButton")
        self.btn_ok.setMinimumWidth(96)
        self.btn_ok.clicked.connect(self._confirm)
        self.countdown_label = QLabel(self._countdown_text())
        self.countdown_label.setObjectName("dimLabel")
        row.addStretch()
        row.addWidget(self.btn_ok)
        row.addWidget(self.countdown_label)
        row.addStretch()
        root.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.btn_ok.setDefault(True)
        self.btn_ok.setFocus()

    def _countdown_text(self) -> str:
        return f"{self._remaining}秒"

    def _confirm(self):
        self._timer.stop()
        self.accept()

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.accept()
            return
        self.countdown_label.setText(self._countdown_text())
