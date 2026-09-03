"""Window / taskbar icon for Report Creator."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QWidget

APP_USER_MODEL_ID = "Reach.ReportCreator"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def app_icon_path() -> Path | None:
    assets = project_root() / "assets"
    for name in ("app.ico", "app.png"):
        path = assets / name
        if path.is_file():
            return path
    return None


def load_app_icon() -> QIcon | None:
    path = app_icon_path()
    if path is None:
        return None
    icon = QIcon(str(path))
    if icon.isNull():
        return None
    return icon


def set_windows_app_id() -> None:
    """So the Windows taskbar uses this app's icon instead of pythonw.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def apply_app_icon(app: QApplication, window: QWidget | None = None) -> None:
    icon = load_app_icon()
    if icon is None:
        return
    app.setWindowIcon(icon)
    if window is not None:
        window.setWindowIcon(icon)
