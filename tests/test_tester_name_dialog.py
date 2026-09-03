import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from src.ui.main_window import MainWindow
from src.ui.tester_name_dialog import TesterNameDialog as NamePrompt


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_tester_name_dialog_has_ok_but_no_cancel():
    _app()
    dialog = NamePrompt("黄佳林")
    box = dialog.findChild(QDialogButtonBox)
    assert box is not None
    assert box.button(QDialogButtonBox.Ok) is not None
    assert box.button(QDialogButtonBox.Cancel) is None
    assert not (dialog.windowFlags() & Qt.WindowCloseButtonHint)
    dialog.accept()
    dialog.close()


def test_tester_name_dialog_escape_does_not_dismiss():
    _app()
    dialog = NamePrompt()
    dialog.show()
    QApplication.processEvents()
    QTest.keyClick(dialog, Qt.Key_Escape)
    QApplication.processEvents()
    assert dialog.isVisible()
    assert dialog.result() != QDialog.Accepted
    dialog.txt_name.setText("展玮鸿")
    box = dialog.findChild(QDialogButtonBox)
    QTest.mouseClick(box.button(QDialogButtonBox.Ok), Qt.LeftButton)
    QApplication.processEvents()
    assert dialog.result() == QDialog.Accepted
    assert dialog.tester_name() == "展玮鸿"
    dialog.close()


def test_startup_loads_saved_tester_and_skips_prompt(monkeypatch):
    _app()
    monkeypatch.setattr("src.ui.main_window.default_tester_name", lambda: "展玮鸿")
    win = MainWindow()
    assert win._session_tester_name == "展玮鸿"
    assert win._tester_prompt_pending is False
    assert "展玮鸿" in win.lbl_tester_title.text()
    assert not win.lbl_tester_title.isHidden()

    prompted = {"called": False}

    def fake_prompt(**_kwargs):
        prompted["called"] = True
        return True

    win._prompt_tester_name = fake_prompt
    win.show()
    QApplication.processEvents()
    QApplication.processEvents()
    assert prompted["called"] is False
    win.close()


def test_startup_prompts_when_no_saved_tester_name(monkeypatch):
    _app()
    monkeypatch.setattr("src.ui.main_window.default_tester_name", lambda: "")
    win = MainWindow()
    assert win._session_tester_name == ""
    assert win._tester_prompt_pending is True
    assert win.lbl_tester_title.isHidden()

    prompted = {"called": False}

    def fake_prompt(**_kwargs):
        prompted["called"] = True
        return True

    win._prompt_tester_name = fake_prompt
    win.show()
    QApplication.processEvents()
    QApplication.processEvents()
    assert prompted["called"] is True
    win.close()
