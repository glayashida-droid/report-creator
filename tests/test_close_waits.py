"""Closing the window waits until background QThreads have returned."""

import sys
import time

from PySide6.QtCore import QThread
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from src.io.cancellable_process import ProcessCancelled, run_cancellable
from src.ui.main_window import MainWindow


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_run_cancellable_kills_the_child():
    started = time.monotonic()

    def cancelled():
        return time.monotonic() - started > 0.15

    try:
        run_cancellable(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=10,
            cancelled=cancelled,
        )
    except ProcessCancelled:
        pass
    else:
        raise AssertionError("child was not cancelled")
    assert time.monotonic() - started < 3


def test_close_waits_until_background_thread_stops():
    _app()
    win = MainWindow()
    win.show()
    QApplication.processEvents()
    seen = {}

    class _Hold(QThread):
        def run(self):
            while not self.isInterruptionRequested():
                self.msleep(15)
            seen["visible"] = win.isVisible()

    worker = _Hold(win)
    worker.start()
    win._catalog_warm_worker = worker
    try:
        event = QCloseEvent()
        win.closeEvent(event)
        assert event.isAccepted()
        assert not worker.isRunning()
        assert seen.get("visible") is True
    finally:
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(2000)
        win.deleteLater()
        QApplication.processEvents()


def test_close_back_leaves_background_thread_running():
    _app()
    win = MainWindow()
    worker_box = {}

    class _Hold(QThread):
        def run(self):
            while not self.isInterruptionRequested():
                self.msleep(15)

    worker = _Hold(win)
    worker_box["worker"] = worker
    worker.start()
    win._catalog_warm_worker = worker
    win._has_unsaved_changes = lambda: True
    win._confirm_unsaved_exit = lambda: "back"
    try:
        event = QCloseEvent()
        win.closeEvent(event)
        assert not event.isAccepted()
        assert worker.isRunning()
        assert win._shutting_down is False
    finally:
        worker.requestInterruption()
        worker.wait(2000)
        win.deleteLater()
        QApplication.processEvents()
