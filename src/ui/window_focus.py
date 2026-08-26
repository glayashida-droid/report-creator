"""Force a Qt window to the OS foreground (needed after file-manager drag-drop)."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QWidget


def force_window_foreground(widget: QWidget | None) -> None:
    """Raise *widget* and make this process the frontmost app.

    Drag-drop from Finder / Explorer often leaves our dialog visible but inactive
    (Dock / taskbar flash). Qt raise_/activateWindow alone is not enough.
    """
    if widget is None:
        return
    win = widget.window()
    win.raise_()
    win.activateWindow()
    app = QApplication.instance()
    if app is not None:
        app.setActiveWindow(win)

    if sys.platform == "win32":
        _windows_set_foreground(win)
    elif sys.platform == "darwin":
        _macos_activate()


def _windows_set_foreground(win: QWidget) -> None:
    try:
        import ctypes
    except ImportError:
        return

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = int(win.winId())
    if not hwnd:
        return

    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.BringWindowToTop(hwnd)

    foreground = user32.GetForegroundWindow()
    if foreground == hwnd:
        return

    fore_tid = user32.GetWindowThreadProcessId(foreground, None)
    cur_tid = kernel32.GetCurrentThreadId()
    attached = False
    if fore_tid and fore_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(fore_tid, cur_tid, True))
    try:
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(fore_tid, cur_tid, False)


def _macos_activate() -> None:
    try:
        import ctypes
        import ctypes.util
    except ImportError:
        return

    lib_name = ctypes.util.find_library("objc")
    if not lib_name:
        return
    objc = ctypes.cdll.LoadLibrary(lib_name)
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.objc_msgSend.restype = ctypes.c_void_p
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    ns_app_cls = objc.objc_getClass(b"NSApplication")
    shared_sel = objc.sel_registerName(b"sharedApplication")
    app = objc.objc_msgSend(ns_app_cls, shared_sel)
    if not app:
        return
    activate_sel = objc.sel_registerName(b"activateIgnoringOtherApps:")
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
    objc.objc_msgSend(app, activate_sel, True)
