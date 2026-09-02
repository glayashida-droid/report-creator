import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

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
