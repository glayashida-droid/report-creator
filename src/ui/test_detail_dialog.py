from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QLineEdit, QComboBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QHeaderView, QDateEdit, QGroupBox, QMessageBox)
from PySide6.QtCore import Qt, QDate
from src.models.project_state import TestNode, TestSample, TestResult

class TestDetailDialog(QDialog):
    def __init__(self, node_data: TestNode, standards: list, equipments: list, parent=None):
        super().__init__(parent)
        self.node_data = node_data
        self.standards = standards # List of dicts
        self.equipments = equipments # List of dicts
        
        # Get project bounds if available
        self.proj_start_date = None
        self.proj_end_date = None
        
        p = self.parent()
        while p and not hasattr(p, 'state'):
            p = p.parent()
        if p and hasattr(p, 'state'):
            try:
                if p.state.test_start_date:
                    self.proj_start_date = QDate.fromString(p.state.test_start_date, "yyyy-MM-dd")
                if p.state.test_end_date:
                    self.proj_end_date = QDate.fromString(p.state.test_end_date, "yyyy-MM-dd")
            except:
                pass
        
        self.setWindowTitle(f"编辑明细 - {node_data.test_name}")
        self.resize(600, 500)
        
        self.init_ui()
        self.load_data()

    def _make_calendar_date_edit(self):
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setDate(QDate.currentDate())
        date_edit.lineEdit().setReadOnly(True)
        return date_edit
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 1. Dates
        date_group = QGroupBox("日期设置")
        date_layout = QHBoxLayout(date_group)
        self.date_start = self._make_calendar_date_edit()
        self.date_end = self._make_calendar_date_edit()
        date_layout.addWidget(QLabel("开始日期:"))
        date_layout.addWidget(self.date_start)
        date_layout.addWidget(QLabel("结束日期:"))
        date_layout.addWidget(self.date_end)
        layout.addWidget(date_group)
        
        # 2. Db Linking
        db_group = QGroupBox("标准与设备")
        db_layout = QVBoxLayout(db_group)
        
        std_layout = QHBoxLayout()
        self.combo_std = QComboBox()
        self.combo_std.addItem("请选择标准...")
        for s in self.standards:
            std_no = s.get("标准号", "")
            if std_no:
                self.combo_std.addItem(str(std_no), userData=s)
        self.combo_std.currentIndexChanged.connect(self.on_std_changed)
                
        self.lbl_std_desc = QLabel("描述: -")
        self.lbl_std_desc.setWordWrap(True)
        std_layout.addWidget(QLabel("测试标准:"))
        std_layout.addWidget(self.combo_std, stretch=1)
        db_layout.addLayout(std_layout)
        db_layout.addWidget(self.lbl_std_desc)
        
        eq_layout = QHBoxLayout()
        self.combo_eq = QComboBox()
        self.combo_eq.addItem("请选择设备...")
        for e in self.equipments:
            eq_name = e.get("设备名称", "")
            eq_model = e.get("型号", "")
            display = f"{eq_name} ({eq_model})" if eq_model else str(eq_name)
            if eq_name:
                self.combo_eq.addItem(display, userData=e)
                
        eq_layout.addWidget(QLabel("测试设备:"))
        eq_layout.addWidget(self.combo_eq, stretch=1)
        db_layout.addLayout(eq_layout)
        
        layout.addWidget(db_group)
        
        # 3. Samples
        sample_group = QGroupBox("样品与结果")
        sample_layout = QVBoxLayout(sample_group)
        
        toolbar = QHBoxLayout()
        self.btn_add_sample = QPushButton("+ 添加样品行")
        self.btn_add_sample.clicked.connect(self.add_sample_row)
        toolbar.addWidget(self.btn_add_sample)
        toolbar.addStretch()
        sample_layout.addLayout(toolbar)
        
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["样品编号", "测试结果"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        sample_layout.addWidget(self.table)
        
        layout.addWidget(sample_group)
        
        # 4. Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self.save_and_close)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
    def on_std_changed(self, index):
        if index > 0:
            std_data = self.combo_std.itemData(index)
            desc = str(std_data.get("标准描述", ""))
            self.lbl_std_desc.setText(f"描述: {desc[:50]}..." if len(desc) > 50 else f"描述: {desc}")
        else:
            self.lbl_std_desc.setText("描述: -")
            
    def add_sample_row(self, sample_id="", result=TestResult.NA):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # ID input
        txt_id = QLineEdit(sample_id)
        self.table.setCellWidget(row, 0, txt_id)
        
        # Result combo
        combo_res = QComboBox()
        for r in TestResult:
            combo_res.addItem(r.value, userData=r)
        combo_res.setCurrentText(result.value)
        self.table.setCellWidget(row, 1, combo_res)
        
    def load_data(self):
        # Dates
        if self.node_data.start_date:
            self.date_start.setDate(QDate.fromString(self.node_data.start_date, "yyyy-MM-dd"))
        else:
            self.date_start.setDate(QDate.currentDate())
            
        if self.node_data.end_date:
            self.date_end.setDate(QDate.fromString(self.node_data.end_date, "yyyy-MM-dd"))
        else:
            self.date_end.setDate(QDate.currentDate())
            
        # Apply bounds if we have them
        if self.proj_start_date and self.proj_start_date.isValid():
            self.date_start.setMinimumDate(self.proj_start_date)
            self.date_end.setMinimumDate(self.proj_start_date)
        if self.proj_end_date and self.proj_end_date.isValid():
            self.date_start.setMaximumDate(self.proj_end_date)
            self.date_end.setMaximumDate(self.proj_end_date)
            
        # Apply bounds if we have them
        if self.proj_start_date and self.proj_start_date.isValid():
            self.date_start.setMinimumDate(self.proj_start_date)
            self.date_end.setMinimumDate(self.proj_start_date)
        if self.proj_end_date and self.proj_end_date.isValid():
            self.date_start.setMaximumDate(self.proj_end_date)
            self.date_end.setMaximumDate(self.proj_end_date)
            
        # Standards
        if self.node_data.standard_id:
            idx = self.combo_std.findText(self.node_data.standard_id)
            if idx >= 0:
                self.combo_std.setCurrentIndex(idx)
                
        # Equipments
        if self.node_data.equipment_name:
            # Simple match by starting with equipment name
            for i in range(self.combo_eq.count()):
                if self.combo_eq.itemText(i).startswith(self.node_data.equipment_name):
                    self.combo_eq.setCurrentIndex(i)
                    break
                    
        # Samples
        for s in self.node_data.samples:
            self.add_sample_row(s.sample_id, s.result)
            
    def save_and_close(self):
        # Validate dates
        if self.date_start.date() > self.date_end.date():
            QMessageBox.warning(self, "错误", "开始日期不能晚于结束日期！")
            return
            
        self.node_data.start_date = self.date_start.date().toString("yyyy-MM-dd")
        self.node_data.end_date = self.date_end.date().toString("yyyy-MM-dd")
        
        # Save standard
        if self.combo_std.currentIndex() > 0:
            std_data = self.combo_std.currentData()
            self.node_data.standard_id = str(std_data.get("标准号", ""))
            self.node_data.standard_desc = str(std_data.get("标准描述", ""))
            self.node_data.evaluation_req = str(std_data.get("评价要求", ""))
        else:
            self.node_data.standard_id = None
            
        # Save equipment
        if self.combo_eq.currentIndex() > 0:
            eq_data = self.combo_eq.currentData()
            self.node_data.equipment_name = str(eq_data.get("设备名称", ""))
        else:
            self.node_data.equipment_name = None
            
        # Save samples
        samples = []
        for row in range(self.table.rowCount()):
            txt_id = self.table.cellWidget(row, 0).text().strip()
            if txt_id:
                combo_res = self.table.cellWidget(row, 1)
                res = combo_res.currentData()
                samples.append(TestSample(sample_id=txt_id, result=res))
                
        self.node_data.samples = samples
        self.accept()
