"""Collect ELP-only fields (rated voltage, incoming method, plan number) before export."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from src.generators.elp_engine import ElpExportFields


class ElpExportDialog(QDialog):
    def __init__(
        self,
        *,
        plan_no: str = "",
        manufacturer_address: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("吉利 ELP 报告")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请确认以下信息："))
        form = QFormLayout()
        self.txt_voltage = QLineEdit()
        self.txt_voltage.setPlaceholderText("留空则报告中该项为空")
        self.txt_source = QLineEdit()
        self.txt_source.setPlaceholderText("留空则报告中该项为空")
        self.txt_plan_no = QLineEdit()
        self.txt_plan_no.setText((plan_no or "").strip())
        self.txt_plan_no.setPlaceholderText("ELP 测试计划编号")
        self.txt_manufacturer_address = None
        form.addRow("额定电压：", self.txt_voltage)
        form.addRow("来样方式：", self.txt_source)
        if manufacturer_address is not None:
            self.txt_manufacturer_address = QLineEdit()
            self.txt_manufacturer_address.setText(manufacturer_address)
            self.txt_manufacturer_address.setPlaceholderText("申请单未解析到生产商地址")
            form.addRow("生产商地址：", self.txt_manufacturer_address)
        form.addRow("测试计划编号：", self.txt_plan_no)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def fields(self) -> ElpExportFields:
        maker = ""
        if self.txt_manufacturer_address is not None:
            maker = self.txt_manufacturer_address.text()
        return ElpExportFields(
            rated_voltage=self.txt_voltage.text(),
            sample_source=self.txt_source.text(),
            plan_no=self.txt_plan_no.text(),
            manufacturer_address=maker,
        )
