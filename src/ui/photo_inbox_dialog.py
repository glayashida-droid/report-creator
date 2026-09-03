"""Dialog: QR + URL for the phone photo inbox."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.io.photo_inbox import PhotoInbox
from src.ui.window_focus import force_window_foreground


class PhotoInboxDialog(QDialog):
    photosReceived = Signal()

    def __init__(self, dest: Path, prefix: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"扫码上传 · {prefix}")
        self.setModal(True)
        self._inbox = PhotoInbox.start(Path(dest), prefix)
        self._count = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        pix = QPixmap()
        pix.loadFromData(PhotoInbox.qr_png_bytes(self._inbox.url))
        self.lbl_qr = QLabel()
        self.lbl_qr.setAlignment(Qt.AlignCenter)
        self.lbl_qr.setPixmap(
            pix.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        layout.addWidget(self.lbl_qr, 0, Qt.AlignHCenter)

        self.lbl_url = QLabel(self._inbox.url)
        self.lbl_url.setObjectName("photoInboxUrl")
        self.lbl_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_url.setWordWrap(True)
        self.lbl_url.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_url)

        hint = (
            "手机与电脑连同一 Wi-Fi 后扫码（或用手输上方地址），"
            "在相册里选 jpg / png 上传。上传后按文件夹名编号。"
        )
        if self._inbox.host == "127.0.0.1":
            hint = "未找到局域网地址，手机扫码将打不开。请确认电脑已连 Wi-Fi 后重试。"
        self.lbl_hint = QLabel(hint)
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setObjectName("photoInboxHint")
        layout.addWidget(self.lbl_hint)

        self.lbl_status = QLabel("等待手机上传…")
        layout.addWidget(self.lbl_status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("完成")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: force_window_foreground(self))

    def _poll(self):
        new = self._inbox.drain_new()
        if not new:
            return
        self._count += len(new)
        self.lbl_status.setText(f"已收到 {self._count} 张")
        self.photosReceived.emit()

    def done(self, result: int):
        self._timer.stop()
        self._inbox.stop()
        super().done(result)
