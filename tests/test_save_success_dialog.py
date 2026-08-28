import sys
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.save_success_dialog import SaveSuccessDialog


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_save_success_dialog_shows_message_and_countdown():
    _app()
    dlg = SaveSuccessDialog(seconds=3)
    assert dlg.windowTitle() == "提示"
    assert dlg.countdown_label.text() == "3秒"
    assert dlg.btn_ok.text() == "确定"


def test_save_success_dialog_confirm_closes_immediately():
    _app()
    dlg = SaveSuccessDialog(seconds=3)
    closed = {"done": False}
    dlg.finished.connect(lambda: closed.__setitem__("done", True))
    dlg.btn_ok.click()
    QApplication.processEvents()
    assert closed["done"]
    assert not dlg._timer.isActive()


def test_save_success_dialog_auto_closes_after_countdown():
    _app()
    dlg = SaveSuccessDialog(seconds=2)
    closed = {"done": False}
    dlg.finished.connect(lambda: closed.__setitem__("done", True))
    dlg._tick()
    assert dlg.countdown_label.text() == "1秒"
    assert not closed["done"]
    dlg._tick()
    QApplication.processEvents()
    assert closed["done"]
    assert not dlg._timer.isActive()


def test_save_detail_button_shows_success_dialog():
    _app()
    win = MainWindow()
    win.state.project_id = "TEST001"
    with patch("src.ui.main_window.SaveSuccessDialog") as mock_dialog_cls:
        mock_dialog = mock_dialog_cls.return_value
        win.leg_graph.btn_save.click()
        QApplication.processEvents()
        mock_dialog_cls.assert_called_once_with(win)
        mock_dialog.exec.assert_called_once()


if __name__ == "__main__":
    test_save_success_dialog_shows_message_and_countdown()
    test_save_success_dialog_confirm_closes_immediately()
    test_save_success_dialog_auto_closes_after_countdown()
    test_save_detail_button_shows_success_dialog()
    print("test_save_success_dialog: ok")
