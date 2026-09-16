"""Collect ELP-only fields (rated voltage, incoming method, plan number) before export."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from src.generators.elp_engine import ElpExportFields


class ElpExportDialog(QDialog):
    def __init__(
        self,
        *,
        plan_no: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("吉利 ELP 报告")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.txt_voltage = QLineEdit()
        self.txt_voltage.setPlaceholderText("留空则报告中该项为空")
        self.txt_source = QLineEdit()
        self.txt_source.setPlaceholderText("留空则报告中该项为空")
        self.txt_plan_no = QLineEdit()
        self.txt_plan_no.setText((plan_no or "").strip())
        self.txt_plan_no.setPlaceholderText("ELP 测试计划编号")
        form.addRow("额定电压：", self.txt_voltage)
        form.addRow("来样方式：", self.txt_source)
        form.addRow("测试计划编号：", self.txt_plan_no)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def fields(self) -> ElpExportFields:
        return ElpExportFields(
            rated_voltage=self.txt_voltage.text(),
            sample_source=self.txt_source.text(),
            plan_no=self.txt_plan_no.text(),
        )
