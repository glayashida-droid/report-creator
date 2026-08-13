from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit, QGroupBox, QMessageBox,
    QTextEdit, QSizePolicy, QAbstractItemView, QScrollArea, QFrame, QWidget,
)
from PySide6.QtCore import Qt, QDate, Signal, QTimer
from src.models.project_state import TestNode, TestSample, TestResult, TestEquipment


def _cell_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text in {"", "nan", "NaT", "None"}:
        return ""
    return text


def _matches_query(query, *fields):
    tokens = (query or "").strip().lower().split()
    if not tokens:
        return True
    blob = " ".join(_cell_text(f) for f in fields).lower()
    return all(token in blob for token in tokens)


class DrawerHeader(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class DrawerSection(QFrame):
    """Collapsible drawer: header stays visible, body toggles."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("drawerSection")
        self._title = title
        self._expanded = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = DrawerHeader()
        self.header.setObjectName("drawerHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setAttribute(Qt.WA_Hover, True)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(12, 8, 12, 8)
        head.setSpacing(8)
        self.lbl_arrow = QLabel("▼")
        self.lbl_arrow.setObjectName("drawerArrow")
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("drawerTitle")
        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("dimLabel")
        self.lbl_summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.lbl_arrow)
        head.addWidget(self.lbl_title)
        head.addStretch()
        head.addWidget(self.lbl_summary, stretch=1)
        self.header.clicked.connect(self.toggle)
        root.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("drawerBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 6, 10, 10)
        self.body_layout.setSpacing(6)
        root.addWidget(self.body)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def set_summary(self, text):
        self.lbl_summary.setText(text or "")
        self.lbl_summary.setVisible(bool(text))

    def toggle(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded):
        self._expanded = bool(expanded)
        self.body.setVisible(self._expanded)
        self.lbl_arrow.setText("▼" if self._expanded else "▶")
        if self._expanded:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        else:
            header_h = max(self.header.sizeHint().height(), 36)
            self.setFixedHeight(header_h)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None:
            lay = parent.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
            parent.updateGeometry()
            parent.adjustSize()


class TestDetailDialog(QDialog):
    def __init__(self, node_data: TestNode, standards: list, equipments: list, parent=None):
        super().__init__(parent)
        self.node_data = node_data
        self.standards = standards or []
        self.equipments = equipments or []

        self.proj_start_date = None
        self.proj_end_date = None
        self._project_state = None

        p = self.parent()
        while p and not hasattr(p, "state"):
            p = p.parent()
        if p and hasattr(p, "state"):
            self._project_state = p.state
            try:
                if p.state.test_start_date:
                    self.proj_start_date = QDate.fromString(p.state.test_start_date, "yyyy-MM-dd")
                if p.state.test_end_date:
                    self.proj_end_date = QDate.fromString(p.state.test_end_date, "yyyy-MM-dd")
            except Exception:
                pass

        self.setWindowTitle(f"编辑明细 - {node_data.test_name}")
        self.resize(860, 760)
        self.setMinimumSize(680, 560)

        self.init_ui()
        self.load_data()

    def _make_calendar_date_edit(self):
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setDate(QDate.currentDate())
        date_edit.lineEdit().setReadOnly(True)
        return date_edit

    def _make_table(self, headers, min_height):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setFixedHeight(min_height)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(False)
        return table

    def _make_group(self, title):
        box = QGroupBox(title)
        box.setObjectName("detailGroup")
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 18, 10, 10)
        lay.setSpacing(6)
        return box, lay

    def init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 8, 2)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        date_group, date_layout = self._make_group("日期设置")
        date_row = QHBoxLayout()
        self.date_start = self._make_calendar_date_edit()
        self.date_end = self._make_calendar_date_edit()
        date_row.addWidget(QLabel("开始日期:"))
        date_row.addWidget(self.date_start)
        date_row.addWidget(QLabel("结束日期:"))
        date_row.addWidget(self.date_end)
        date_layout.addLayout(date_row)
        self._updating_dates = False
        self.date_start.dateChanged.connect(self._on_node_dates_changed)
        self.date_end.dateChanged.connect(self._on_node_dates_changed)
        layout.addWidget(date_group)

        self.drawer_std = DrawerSection("测试标准")
        std_layout = self.drawer_std.body_layout
        self.txt_std_search = QLineEdit()
        self.txt_std_search.setPlaceholderText("搜索标准号 / 章节号 / 试验名称")
        self.txt_std_search.textChanged.connect(self._filter_standards)
        std_layout.addWidget(self.txt_std_search)

        self.std_table = self._make_table(["标准号", "章节号", "试验名称"], 180)
        self.std_table.itemSelectionChanged.connect(self._on_std_selected)
        self.std_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.std_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.std_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        std_layout.addWidget(self.std_table)

        self.lbl_std_pick = QLabel("已选: —")
        self.lbl_std_pick.setObjectName("dimLabel")
        std_layout.addWidget(self.lbl_std_pick)

        std_layout.addWidget(QLabel("描述:"))
        self.txt_std_desc = QTextEdit()
        self.txt_std_desc.setReadOnly(True)
        self.txt_std_desc.setFixedHeight(84)
        self.txt_std_desc.setPlaceholderText("选择标准后显示描述")
        std_layout.addWidget(self.txt_std_desc)
        layout.addWidget(self.drawer_std)

        self.drawer_eq = DrawerSection("测试设备")
        eq_layout = self.drawer_eq.body_layout
        eq_header = QHBoxLayout()
        eq_header.addWidget(QLabel("可多选，点击行或勾选"))
        eq_header.addStretch()
        self.lbl_eq_pick = QLabel("已选 0 台")
        self.lbl_eq_pick.setObjectName("dimLabel")
        eq_header.addWidget(self.lbl_eq_pick)
        eq_layout.addLayout(eq_header)

        self.txt_eq_search = QLineEdit()
        self.txt_eq_search.setPlaceholderText("搜索设备编号或设备名称，如 SHAED、温湿度")
        self.txt_eq_search.textChanged.connect(self._filter_equipments)
        eq_layout.addWidget(self.txt_eq_search)

        self.eq_table = self._make_table(["", "设备编号", "设备名称", "型号"], 200)
        self.eq_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.eq_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.eq_table.setColumnWidth(0, 28)
        self.eq_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.eq_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.eq_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.eq_table.itemChanged.connect(self._on_eq_item_changed)
        self.eq_table.cellClicked.connect(self._on_eq_cell_clicked)
        eq_layout.addWidget(self.eq_table)
        layout.addWidget(self.drawer_eq)

        self.drawer_sample = DrawerSection("样品与结果")
        sample_layout = self.drawer_sample.body_layout
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.btn_add_sample = QPushButton("+ 添加样品行")
        self.btn_add_sample.clicked.connect(lambda: self.add_sample_row())
        toolbar.addWidget(self.btn_add_sample)

        toolbar.addWidget(QLabel("首字母"))
        self.txt_sample_prefix = QLineEdit()
        self.txt_sample_prefix.setPlaceholderText("A")
        self.txt_sample_prefix.setText("A")
        self.txt_sample_prefix.setFixedWidth(40)
        self.txt_sample_prefix.setMaxLength(8)
        toolbar.addWidget(self.txt_sample_prefix)

        toolbar.addWidget(QLabel("起始号"))
        self.txt_sample_start = QLineEdit()
        self.txt_sample_start.setPlaceholderText("01")
        self.txt_sample_start.setText("01")
        self.txt_sample_start.setFixedWidth(48)
        toolbar.addWidget(self.txt_sample_start)

        toolbar.addWidget(QLabel("数量"))
        self.txt_sample_qty = QLineEdit()
        self.txt_sample_qty.setPlaceholderText("3")
        self.txt_sample_qty.setText("3")
        self.txt_sample_qty.setFixedWidth(40)
        toolbar.addWidget(self.txt_sample_qty)

        self.btn_add_appno = QPushButton("添加单号")
        self.btn_add_appno.setToolTip("在已有样品号前加上申请单号，已加过的不会重复加")
        self.btn_add_appno.clicked.connect(self._prepend_application_no)
        toolbar.addWidget(self.btn_add_appno)

        self.btn_gen_samples = QPushButton("生成")
        self.btn_gen_samples.setObjectName("accentButton")
        self.btn_gen_samples.setToolTip("按首字母+起始号+数量生成样品，已存在的编号会跳过")
        self.btn_gen_samples.clicked.connect(self._generate_samples)
        toolbar.addWidget(self.btn_gen_samples)
        toolbar.addStretch()
        sample_layout.addLayout(toolbar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["样品编号", "结果描述", "测试结果"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setMinimumHeight(32)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(0, 158)
        self.table.setColumnWidth(2, 168)
        self.table.setMinimumHeight(400)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sample_layout.addWidget(self.table)
        self._setup_result_header()
        layout.addWidget(self.drawer_sample)
        layout.addStretch(1)

        self.drawer_std.set_expanded(True)
        self.drawer_eq.set_expanded(False)
        self.drawer_sample.set_expanded(False)

        scroll.setWidget(host)
        outer.addWidget(scroll, stretch=1)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self.save_and_close)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        outer.addLayout(btn_layout)

        self._fill_standards()
        self._fill_equipments()
        self._schedule_result_header_sync()

    def _setup_result_header(self):
        header = self.table.horizontalHeader()
        self._header_sync_pending = False
        self.combo_bulk_result = QComboBox(header.viewport())
        self.combo_bulk_result.setObjectName("bulkResultCombo")
        self.combo_bulk_result.setFocusPolicy(Qt.StrongFocus)
        self.combo_bulk_result.addItem("—")
        for r in TestResult:
            self.combo_bulk_result.addItem(r.value)
        self.combo_bulk_result.activated.connect(self._apply_bulk_result)
        header.sectionResized.connect(lambda *_: self._schedule_result_header_sync())
        header.geometriesChanged.connect(self._schedule_result_header_sync)
        self.table.horizontalScrollBar().valueChanged.connect(
            lambda *_: self._schedule_result_header_sync()
        )
        self.table.verticalScrollBar().rangeChanged.connect(
            lambda *_: self._schedule_result_header_sync()
        )
        self.drawer_sample.header.clicked.connect(self._schedule_result_header_sync)

    def _schedule_result_header_sync(self):
        if getattr(self, "_header_sync_pending", False):
            return
        self._header_sync_pending = True
        QTimer.singleShot(0, self._sync_result_header)

    def _sync_result_header(self):
        self._header_sync_pending = False
        if not hasattr(self, "combo_bulk_result"):
            return
        header = self.table.horizontalHeader()
        x = header.sectionViewportPosition(2)
        section_w = header.sectionSize(2)
        combo_w = 86
        combo_h = 24
        left_pad = 8
        gap = 6
        right_margin = 12
        label = header.model().headerData(2, Qt.Horizontal) or "测试结果"
        label_w = header.fontMetrics().horizontalAdvance(str(label))
        cx = x + left_pad + label_w + gap
        max_cx = x + max(section_w - combo_w - right_margin, 0)
        cx = min(max(cx, x + left_pad), max_cx)
        cy = max((header.height() - combo_h) // 2, 2)
        self.combo_bulk_result.setGeometry(cx, cy, combo_w, combo_h)
        visible = section_w >= 90
        self.combo_bulk_result.setVisible(visible)
        if visible:
            self.combo_bulk_result.raise_()

    def _apply_bulk_result(self, index):
        text = self.combo_bulk_result.itemText(index) if index >= 0 else self.combo_bulk_result.currentText()
        if text in ("", "—"):
            return
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 2)
            if combo is None:
                continue
            pos = combo.findText(text)
            if pos >= 0:
                combo.setCurrentIndex(pos)

    def _fill_standards(self):
        self.std_table.setRowCount(0)
        for std in self.standards:
            std_no = _cell_text(std.get("标准号"))
            chapter = _cell_text(std.get("章节号"))
            test_name = _cell_text(std.get("试验名称"))
            if not (std_no or chapter or test_name):
                continue
            row = self.std_table.rowCount()
            self.std_table.insertRow(row)
            for col, text in enumerate((std_no, chapter, test_name)):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.UserRole, std)
                self.std_table.setItem(row, col, item)

    def _fill_equipments(self):
        self.eq_table.blockSignals(True)
        self.eq_table.setRowCount(0)
        for eq in self.equipments:
            code = _cell_text(eq.get("设备编号"))
            name = _cell_text(eq.get("设备名称"))
            model = _cell_text(eq.get("型号"))
            if not (code or name):
                continue
            row = self.eq_table.rowCount()
            self.eq_table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, eq)
            self.eq_table.setItem(row, 0, chk)
            self.eq_table.setItem(row, 1, QTableWidgetItem(code))
            self.eq_table.setItem(row, 2, QTableWidgetItem(name))
            self.eq_table.setItem(row, 3, QTableWidgetItem(model))
        self.eq_table.blockSignals(False)
        self._refresh_eq_summary()

    def _filter_standards(self, query=""):
        for row in range(self.std_table.rowCount()):
            std_no = self.std_table.item(row, 0).text() if self.std_table.item(row, 0) else ""
            chapter = self.std_table.item(row, 1).text() if self.std_table.item(row, 1) else ""
            name = self.std_table.item(row, 2).text() if self.std_table.item(row, 2) else ""
            self.std_table.setRowHidden(row, not _matches_query(query, std_no, chapter, name))

    def _filter_equipments(self, query=""):
        for row in range(self.eq_table.rowCount()):
            code = self.eq_table.item(row, 1).text() if self.eq_table.item(row, 1) else ""
            name = self.eq_table.item(row, 2).text() if self.eq_table.item(row, 2) else ""
            self.eq_table.setRowHidden(row, not _matches_query(query, code, name))

    def _current_std(self):
        rows = self.std_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.std_table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def _on_std_selected(self):
        std = self._current_std()
        if not std:
            self.lbl_std_pick.setText("已选: —")
            self.drawer_std.set_summary("")
            self.txt_std_desc.setPlainText("")
            self._apply_result_desc_to_rows("")
            return
        std_no = _cell_text(std.get("标准号"))
        chapter = _cell_text(std.get("章节号"))
        test_name = _cell_text(std.get("试验名称"))
        parts = [p for p in (std_no, chapter, test_name) if p]
        self.lbl_std_pick.setText("已选: " + "  /  ".join(parts) if parts else "已选: —")
        self.drawer_std.set_summary("  /  ".join(parts) if parts else "")
        desc = _cell_text(std.get("标准描述"))
        self.txt_std_desc.setPlainText(desc or "-")
        self._apply_result_desc_to_rows(_cell_text(std.get("结果描述")))

    def _on_eq_item_changed(self, item):
        if item and item.column() == 0:
            self._refresh_eq_summary()

    def _on_eq_cell_clicked(self, row, col):
        if col == 0:
            return
        chk = self.eq_table.item(row, 0)
        if chk is None:
            return
        chk.setCheckState(Qt.Unchecked if chk.checkState() == Qt.Checked else Qt.Checked)

    def _refresh_eq_summary(self):
        selected = self._selected_equipments()
        if not selected:
            self.lbl_eq_pick.setText("已选 0 台")
            self.drawer_eq.set_summary("未选择")
            return
        preview = "、".join(e.code or e.name for e in selected[:4])
        extra = f" 等{len(selected)}台" if len(selected) > 4 else ""
        text = f"已选 {len(selected)} 台：{preview}{extra}"
        self.lbl_eq_pick.setText(text)
        self.drawer_eq.set_summary(f"{len(selected)} 台  {preview}{extra}")

    def _selected_equipments(self):
        picked = []
        for row in range(self.eq_table.rowCount()):
            chk = self.eq_table.item(row, 0)
            if chk is None or chk.checkState() != Qt.Checked:
                continue
            data = chk.data(Qt.UserRole) or {}
            picked.append(TestEquipment(
                name=_cell_text(data.get("设备名称")),
                code=_cell_text(data.get("设备编号")),
                model=_cell_text(data.get("型号")),
            ))
        return picked

    def _current_result_desc(self):
        std = self._current_std()
        if std:
            return _cell_text(std.get("结果描述"))
        return _cell_text(getattr(self.node_data, "result_desc", None))

    def _apply_result_desc_to_rows(self, text):
        text = text or ""
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 1)
            if widget is not None:
                widget.setText(text)
                widget.setCursorPosition(0)

    def add_sample_row(self, sample_id="", result=TestResult.NA, result_desc=None):
        if not isinstance(sample_id, str):
            sample_id = ""
        row = self.table.rowCount()
        self.table.insertRow(row)
        txt_id = QLineEdit(sample_id)
        txt_id.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        txt_id.setStyleSheet("padding: 1px 4px;")
        self.table.setCellWidget(row, 0, txt_id)
        txt_desc = QLineEdit(result_desc if result_desc is not None else self._current_result_desc())
        txt_desc.setReadOnly(True)
        txt_desc.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        txt_desc.setStyleSheet("padding: 1px 4px;")
        txt_desc.setPlaceholderText("选择标准后自动填入")
        txt_desc.setCursorPosition(0)
        self.table.setCellWidget(row, 1, txt_desc)
        combo_res = QComboBox()
        for r in TestResult:
            combo_res.addItem(r.value, userData=r)
        bulk = ""
        if hasattr(self, "combo_bulk_result"):
            bulk = self.combo_bulk_result.currentText()
        if bulk in {r.value for r in TestResult}:
            combo_res.setCurrentText(bulk)
        else:
            combo_res.setCurrentText(result.value)
        self.table.setCellWidget(row, 2, combo_res)
        self._refresh_sample_summary()
        self._schedule_result_header_sync()

    def _existing_sample_ids(self):
        ids = []
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if widget is None:
                continue
            text = widget.text().strip()
            if text:
                ids.append(text)
        return ids

    def _application_no(self):
        state = self._project_state
        if state is None:
            return ""
        fields = getattr(state, "application_fields", None) or {}
        return (fields.get("申请单号") or getattr(state, "project_id", "") or "").strip()

    @staticmethod
    def _format_seq(number):
        """At least 2 digits; 100+ stays as 3+ digits."""
        return f"{int(number):02d}"

    def _bare_and_prefixed(self, suffix, appno):
        names = {suffix}
        if appno:
            names.add(f"{appno}-{suffix}")
        return names

    def _generate_samples(self):
        prefix = self.txt_sample_prefix.text().strip()
        start_raw = self.txt_sample_start.text().strip()
        qty_raw = self.txt_sample_qty.text().strip()
        if not prefix:
            QMessageBox.warning(self, "提示", "请输入首字母，例如 A")
            return
        if not start_raw.isdigit():
            QMessageBox.warning(self, "提示", "起始号请输入数字，例如 01")
            return
        if not qty_raw.isdigit() or int(qty_raw) < 1:
            QMessageBox.warning(self, "提示", "数量请输入正整数")
            return

        start = int(start_raw)
        qty = int(qty_raw)
        existing = set(self._existing_sample_ids())
        appno = self._application_no()
        added = 0
        for i in range(qty):
            suffix = f"{prefix}{self._format_seq(start + i)}"
            if existing.intersection(self._bare_and_prefixed(suffix, appno)):
                continue
            self.add_sample_row(suffix)
            existing.add(suffix)
            added += 1
        if added == 0:
            QMessageBox.information(self, "提示", "这些编号已经存在，未重复生成。")
        self._schedule_result_header_sync()

    def _prepend_application_no(self):
        appno = self._application_no()
        if not appno:
            QMessageBox.warning(self, "提示", "当前没有申请单号，请先在主界面加载项目。")
            return
        marker = f"{appno}-"
        changed = 0
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if widget is None:
                continue
            text = widget.text().strip()
            if not text or text.startswith(marker):
                continue
            widget.setText(marker + text)
            changed += 1
        if changed == 0:
            QMessageBox.information(self, "提示", "没有需要添加单号的样品，或已经全部加过。")

    def _refresh_sample_summary(self):
        n = self.table.rowCount() if hasattr(self, "table") else 0
        self.drawer_sample.set_summary(f"{n} 行" if n else "未添加")

    def load_data(self):
        if self.node_data.start_date:
            self.date_start.setDate(QDate.fromString(self.node_data.start_date, "yyyy-MM-dd"))
        else:
            self.date_start.setDate(QDate.currentDate())

        if self.node_data.end_date:
            self.date_end.setDate(QDate.fromString(self.node_data.end_date, "yyyy-MM-dd"))
        else:
            self.date_end.setDate(QDate.currentDate())

        if self.proj_start_date and self.proj_start_date.isValid():
            self.date_start.setMinimumDate(self.proj_start_date)
            self.date_end.setMinimumDate(self.proj_start_date)
        if self.proj_end_date and self.proj_end_date.isValid():
            self.date_start.setMaximumDate(self.proj_end_date)
            self.date_end.setMaximumDate(self.proj_end_date)

        self._on_node_dates_changed()
        self._restore_standard()
        self._restore_equipments()

        for s in self.node_data.samples:
            self.add_sample_row(
                s.sample_id,
                s.result,
                getattr(s, "result_desc", None) or getattr(self.node_data, "result_desc", None),
            )
        self._refresh_sample_summary()

    def _restore_standard(self):
        want_id = _cell_text(self.node_data.standard_id)
        want_ch = _cell_text(self.node_data.standard_chapter)
        want_name = _cell_text(self.node_data.standard_test_name)
        if not (want_id or want_ch or want_name):
            return
        fallback = None
        for row in range(self.std_table.rowCount()):
            item = self.std_table.item(row, 0)
            std = item.data(Qt.UserRole) if item else None
            if not std:
                continue
            std_no = _cell_text(std.get("标准号"))
            chapter = _cell_text(std.get("章节号"))
            test_name = _cell_text(std.get("试验名称"))
            if want_ch or want_name:
                if std_no == want_id and (not want_ch or chapter == want_ch) and (
                    not want_name or test_name == want_name
                ):
                    self.std_table.selectRow(row)
                    self.std_table.scrollToItem(item)
                    return
            elif std_no == want_id and fallback is None:
                fallback = row
        if fallback is not None:
            self.std_table.selectRow(fallback)
            item = self.std_table.item(fallback, 0)
            if item:
                self.std_table.scrollToItem(item)

    def _restore_equipments(self):
        codes = {_cell_text(e.code) for e in (self.node_data.equipments or []) if _cell_text(e.code)}
        names = {_cell_text(e.name) for e in (self.node_data.equipments or []) if _cell_text(e.name)}
        legacy = _cell_text(self.node_data.equipment_name)
        self.eq_table.blockSignals(True)
        for row in range(self.eq_table.rowCount()):
            chk = self.eq_table.item(row, 0)
            data = chk.data(Qt.UserRole) if chk else {}
            code = _cell_text((data or {}).get("设备编号"))
            name = _cell_text((data or {}).get("设备名称"))
            checked = False
            if codes and code in codes:
                checked = True
            elif names and name in names:
                checked = True
            elif not codes and not names and legacy:
                if code and code in legacy:
                    checked = True
                elif name and (legacy == name or legacy.startswith(name)):
                    checked = True
            if chk is not None:
                chk.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.eq_table.blockSignals(False)
        self._refresh_eq_summary()

    def _project_date_bounds(self):
        lo = self.proj_start_date if self.proj_start_date and self.proj_start_date.isValid() else QDate(1000, 1, 1)
        hi = self.proj_end_date if self.proj_end_date and self.proj_end_date.isValid() else QDate(9999, 12, 31)
        return lo, hi

    def _on_node_dates_changed(self, *_args):
        """Node start date must be on or before end date."""
        if getattr(self, "_updating_dates", False):
            return
        self._updating_dates = True
        try:
            lo, hi = self._project_date_bounds()
            self.date_start.setMinimumDate(lo)
            self.date_start.setMaximumDate(hi)
            self.date_end.setMinimumDate(lo)
            self.date_end.setMaximumDate(hi)

            start = self.date_start.date()
            end = self.date_end.date()
            source = self.sender()

            if source is self.date_start:
                if start > end:
                    end = start
                    self.date_end.setDate(end)
            elif source is self.date_end:
                if end < start:
                    start = end
                    self.date_start.setDate(start)
            elif start > end:
                end = start
                self.date_end.setDate(end)

            self.date_start.setMinimumDate(lo)
            self.date_start.setMaximumDate(hi)
            self.date_end.setMinimumDate(start)
            self.date_end.setMaximumDate(hi)
        finally:
            self._updating_dates = False

    def save_and_close(self):
        if self.date_start.date() > self.date_end.date():
            QMessageBox.warning(self, "错误", "开始日期不能晚于结束日期！")
            return

        self.node_data.start_date = self.date_start.date().toString("yyyy-MM-dd")
        self.node_data.end_date = self.date_end.date().toString("yyyy-MM-dd")

        std = self._current_std()
        if std:
            self.node_data.standard_id = _cell_text(std.get("标准号")) or None
            self.node_data.standard_chapter = _cell_text(std.get("章节号")) or None
            self.node_data.standard_test_name = _cell_text(std.get("试验名称")) or None
            self.node_data.standard_desc = _cell_text(std.get("标准描述")) or None
            self.node_data.result_desc = _cell_text(std.get("结果描述")) or None
            self.node_data.evaluation_req = _cell_text(std.get("评价要求")) or None
        else:
            self.node_data.standard_id = None
            self.node_data.standard_chapter = None
            self.node_data.standard_test_name = None
            self.node_data.standard_desc = None
            self.node_data.result_desc = None
            self.node_data.evaluation_req = None

        picked = self._selected_equipments()
        self.node_data.equipments = picked
        if picked:
            self.node_data.equipment_name = "；".join(
                " ".join(p for p in (e.code, e.name) if p) for e in picked
            )
        else:
            self.node_data.equipment_name = None

        samples = []
        for row in range(self.table.rowCount()):
            txt_id = self.table.cellWidget(row, 0).text().strip()
            if txt_id:
                desc_w = self.table.cellWidget(row, 1)
                combo_res = self.table.cellWidget(row, 2)
                res = combo_res.currentData()
                desc = desc_w.text().strip() if desc_w else ""
                samples.append(TestSample(
                    sample_id=txt_id,
                    result=res,
                    result_desc=desc or None,
                ))
        self.node_data.samples = samples
        self.accept()
