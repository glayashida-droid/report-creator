import math
import re
from datetime import date, datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit, QGroupBox, QMessageBox,
    QTextEdit, QSizePolicy, QAbstractItemView, QScrollArea, QFrame, QWidget,
    QStyledItemDelegate, QStyle, QStyleOptionViewItem,
)
from PySide6.QtCore import Qt, QDate, Signal, QTimer, QEvent, QPoint
from PySide6.QtGui import QColor, QCursor
from src.models.project_state import TestNode, TestSample, TestResult, TestEquipment, TestStandard

_EQ_EXPIRED_ROLE = Qt.UserRole + 1
_EXPIRED_RED = QColor("#FF5555")
_DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text in {"", "nan", "NaT", "None"}:
        return ""
    return text


def _legacy_equipment_codes(legacy_name):
    codes = []
    for part in _cell_text(legacy_name).split("；"):
        token = part.strip().split()[0] if part.strip() else ""
        if token:
            codes.append(token)
    return codes


def equipment_should_restore(code, name, saved, legacy_name=""):
    """Match a catalog row to saved picks by equipment code, never by shared name."""
    saved = list(saved or [])
    codes = {_cell_text(e.code) for e in saved if _cell_text(getattr(e, "code", ""))}
    if codes:
        return bool(code) and code in codes
    names = {_cell_text(e.name) for e in saved if _cell_text(getattr(e, "name", ""))}
    if names:
        return bool(name) and name in names
    legacy_codes = _legacy_equipment_codes(legacy_name)
    return bool(code) and code in legacy_codes


def _parse_qdate(value):
    """Best-effort parse of Excel / cell values into a QDate."""
    if value is None or isinstance(value, float) and math.isnan(value):
        return QDate()
    if isinstance(value, QDate):
        return value if value.isValid() else QDate()
    if isinstance(value, datetime):
        return QDate(value.year, value.month, value.day)
    if isinstance(value, date):
        return QDate(value.year, value.month, value.day)
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if callable(to_pydatetime):
        try:
            dt = to_pydatetime()
            return QDate(dt.year, dt.month, dt.day)
        except Exception:
            pass
    text = _cell_text(value)
    if not text:
        return QDate()
    match = _DATE_RE.search(text.replace("\n", " "))
    if not match:
        return QDate()
    parsed = QDate(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return parsed if parsed.isValid() else QDate()


def _format_cal_date(value):
    parsed = _parse_qdate(value)
    if parsed.isValid():
        return parsed.toString("yyyy-MM-dd")
    return _cell_text(value).replace("\n", " ")


def _is_equipment_expired(cal_value, end_date):
    """Expired when planned calibration date is strictly before the test end date."""
    cal = _parse_qdate(cal_value)
    if not cal.isValid() or end_date is None or not end_date.isValid():
        return False
    return cal < end_date


class ExpiredNameDelegate(QStyledItemDelegate):
    """Paint equipment names red when the row is marked expired (QSS ignores item foreground)."""

    def paint(self, painter, option, index):
        if not index.data(_EQ_EXPIRED_ROLE):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = option.widget
        style = (widget or self.parent()).style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        painter.save()
        painter.setPen(_EXPIRED_RED)
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget)
        if not rect.isValid():
            rect = opt.rect.adjusted(4, 0, -4, 0)
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


class FollowTip(QLabel):
    """Small annotation that tracks the cursor."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("expiredFollowTip")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.hide()

    def follow(self, global_pos):
        self.adjustSize()
        self.move(global_pos + QPoint(14, 16))
        if not self.isVisible():
            self.show()
        self.raise_()


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


class ElidedLabel(QLabel):
    """Single-line label that ellipsizes instead of wrapping."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text or ""
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        super().setText(self._full)
        self.setToolTip(self._full)

    def setText(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        metrics = self.fontMetrics()
        super().setText(metrics.elidedText(self._full, Qt.ElideRight, max(self.width(), 1)))


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
        self.header.setFixedHeight(36)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(12, 6, 12, 6)
        head.setSpacing(8)
        self.lbl_arrow = QLabel("▼")
        self.lbl_arrow.setObjectName("drawerArrow")
        self.lbl_arrow.setFixedWidth(14)
        self.lbl_title = ElidedLabel(title)
        self.lbl_title.setObjectName("drawerTitle")
        self.lbl_summary = ElidedLabel("")
        self.lbl_summary.setObjectName("dimLabel")
        self.lbl_summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.lbl_arrow)
        head.addWidget(self.lbl_title, stretch=1)
        head.addWidget(self.lbl_summary, stretch=2)
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
            self.setFixedHeight(self.header.height())
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
        self._std_pick_order = []
        self._std_updating = False
        self._cond_edits = {}
        self._cond_editors = {}
        self._cond_drawers = []
        self._eval_edits = {}
        self._eval_editors = {}
        self._eval_drawers = []
        self._result_edits = {}

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

    def _install_header_clear_button(self, table, on_clear):
        header = table.horizontalHeader()
        btn = QPushButton("✕", header.viewport())
        btn.setObjectName("headerClearButton")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setToolTip("取消当前多选")
        btn.clicked.connect(on_clear)
        header.sectionClicked.connect(lambda logical, cb=on_clear: cb() if logical == 0 else None)

        def sync(*_args, t=table, b=btn):
            self._sync_header_clear_button(t, b)

        header.sectionResized.connect(sync)
        header.geometriesChanged.connect(sync)
        table.horizontalScrollBar().valueChanged.connect(sync)
        QTimer.singleShot(0, sync)
        return btn

    def _sync_header_clear_button(self, table, btn):
        header = table.horizontalHeader()
        x = header.sectionViewportPosition(0)
        w = header.sectionSize(0)
        h = header.height()
        size = min(18, max(w - 6, 12), max(h - 8, 12))
        btn.setGeometry(x + max((w - size) // 2, 1), max((h - size) // 2, 1), size, size)
        btn.raise_()

    def _clear_multiselect(self, table):
        table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                chk = table.item(row, 0)
                if chk is not None and chk.checkState() != Qt.Unchecked:
                    chk.setCheckState(Qt.Unchecked)
        finally:
            table.blockSignals(False)
        if table is self.std_table:
            self._std_pick_order = []
            self._refresh_std_summary()
        elif table is self.eq_table:
            self._refresh_eq_summary()

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
        std_layout.addWidget(QLabel("可多选，点击行或勾选，顺序按勾选先后"))

        self.txt_std_search = QLineEdit()
        self.txt_std_search.setPlaceholderText("搜索标准号 / 章节号 / 试验名称")
        self.txt_std_search.textChanged.connect(self._filter_standards)
        std_layout.addWidget(self.txt_std_search)

        self.std_table = self._make_table(["", "标准号", "章节号", "试验名称"], 180)
        self.std_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.std_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.std_table.setColumnWidth(0, 32)
        self.std_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.std_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.std_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.std_table.itemChanged.connect(self._on_std_item_changed)
        self.std_table.cellClicked.connect(self._on_std_cell_clicked)
        self._std_clear_btn = self._install_header_clear_button(
            self.std_table, lambda: self._clear_multiselect(self.std_table)
        )
        std_layout.addWidget(self.std_table)

        method_row = QHBoxLayout()
        method_row.setContentsMargins(0, 2, 0, 2)
        method_row.setSpacing(8)
        method_row.addWidget(QLabel("检测方法:"))
        self.txt_std_method = QLineEdit()
        self.txt_std_method.setReadOnly(True)
        self.txt_std_method.setPlaceholderText("勾选后按顺序显示标准号 / 章节号")
        method_row.addWidget(self.txt_std_method, stretch=1)
        std_layout.addLayout(method_row)

        std_layout.addWidget(QLabel("检测条件:"))
        self.cond_host = QWidget()
        self.cond_layout = QVBoxLayout(self.cond_host)
        self.cond_layout.setContentsMargins(0, 0, 0, 0)
        self.cond_layout.setSpacing(4)
        std_layout.addWidget(self.cond_host)

        std_layout.addWidget(QLabel("评判要求:"))
        self.eval_host = QWidget()
        self.eval_layout = QVBoxLayout(self.eval_host)
        self.eval_layout.setContentsMargins(0, 0, 0, 0)
        self.eval_layout.setSpacing(4)
        std_layout.addWidget(self.eval_host)

        std_layout.addWidget(QLabel("结果描述（按勾选顺序分列，可编辑）:"))
        self.result_desc_table = self._make_table(
            ["标准号", "章节号", "试验名称", "结果描述"], 160
        )
        self.result_desc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.result_desc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.result_desc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.result_desc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        std_layout.addWidget(self.result_desc_table)
        layout.addWidget(self.drawer_std)

        self.drawer_eq = DrawerSection("测试设备")
        eq_layout = self.drawer_eq.body_layout
        eq_layout.addWidget(QLabel("可多选，点击行或勾选"))

        self.txt_eq_search = QLineEdit()
        self.txt_eq_search.setPlaceholderText("搜索设备编号或设备名称，如 SHAED、温湿度")
        self.txt_eq_search.textChanged.connect(self._filter_equipments)
        eq_layout.addWidget(self.txt_eq_search)

        self.eq_table = self._make_table(["", "设备编号", "设备名称", "型号", "校准有效期"], 200)
        self.eq_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.eq_table.setMouseTracking(True)
        self.eq_table.viewport().setMouseTracking(True)
        self.eq_table.viewport().installEventFilter(self)
        self.eq_table.setItemDelegateForColumn(2, ExpiredNameDelegate(self.eq_table))
        eq_header_view = self.eq_table.horizontalHeader()
        eq_header_view.setStretchLastSection(False)
        eq_header_view.setSectionResizeMode(0, QHeaderView.Fixed)
        self.eq_table.setColumnWidth(0, 32)
        eq_header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        eq_header_view.setSectionResizeMode(2, QHeaderView.Stretch)
        eq_header_view.setSectionResizeMode(3, QHeaderView.Stretch)
        eq_header_view.setSectionResizeMode(4, QHeaderView.Fixed)
        self.eq_table.setColumnWidth(4, 116)
        self.eq_table.itemChanged.connect(self._on_eq_item_changed)
        self.eq_table.cellClicked.connect(self._on_eq_cell_clicked)
        self._eq_clear_btn = self._install_header_clear_button(
            self.eq_table, lambda: self._clear_multiselect(self.eq_table)
        )
        eq_layout.addWidget(self.eq_table)
        self._eq_expired_tip = FollowTip("已过期", self)
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

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["样品编号", "测试结果"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setMinimumHeight(32)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(1, 168)
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
        x = header.sectionViewportPosition(1)
        section_w = header.sectionSize(1)
        combo_w = 86
        combo_h = 24
        left_pad = 8
        gap = 6
        right_margin = 12
        label = header.model().headerData(1, Qt.Horizontal) or "测试结果"
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
            combo = self.table.cellWidget(row, 1)
            if combo is None:
                continue
            pos = combo.findText(text)
            if pos >= 0:
                combo.setCurrentIndex(pos)

    def _fill_standards(self):
        self.std_table.blockSignals(True)
        self.std_table.setRowCount(0)
        for std in self.standards:
            std_no = _cell_text(std.get("标准号"))
            chapter = _cell_text(std.get("章节号"))
            test_name = _cell_text(std.get("试验名称"))
            if not (std_no or chapter or test_name):
                continue
            row = self.std_table.rowCount()
            self.std_table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, std)
            self.std_table.setItem(row, 0, chk)
            self.std_table.setItem(row, 1, QTableWidgetItem(std_no))
            self.std_table.setItem(row, 2, QTableWidgetItem(chapter))
            self.std_table.setItem(row, 3, QTableWidgetItem(test_name))
        self.std_table.blockSignals(False)
        self._refresh_std_summary()

    def _fill_equipments(self):
        self.eq_table.blockSignals(True)
        self.eq_table.setRowCount(0)
        for eq in self.equipments:
            code = _cell_text(eq.get("设备编号"))
            name = _cell_text(eq.get("设备名称"))
            model = _cell_text(eq.get("型号"))
            cal = _format_cal_date(eq.get("计划校准时间"))
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
            self.eq_table.setItem(row, 4, QTableWidgetItem(cal))
        self.eq_table.blockSignals(False)
        self._refresh_eq_expiry()
        self._refresh_eq_summary()

    def _filter_standards(self, query=""):
        for row in range(self.std_table.rowCount()):
            std_no = self.std_table.item(row, 1).text() if self.std_table.item(row, 1) else ""
            chapter = self.std_table.item(row, 2).text() if self.std_table.item(row, 2) else ""
            name = self.std_table.item(row, 3).text() if self.std_table.item(row, 3) else ""
            self.std_table.setRowHidden(row, not _matches_query(query, std_no, chapter, name))

    def _filter_equipments(self, query=""):
        for row in range(self.eq_table.rowCount()):
            code = self.eq_table.item(row, 1).text() if self.eq_table.item(row, 1) else ""
            name = self.eq_table.item(row, 2).text() if self.eq_table.item(row, 2) else ""
            self.eq_table.setRowHidden(row, not _matches_query(query, code, name))

    @staticmethod
    def _std_key(std):
        return (
            _cell_text((std or {}).get("标准号")),
            _cell_text((std or {}).get("章节号")),
            _cell_text((std or {}).get("试验名称")),
        )

    def _on_std_item_changed(self, item):
        if self._std_updating or item is None or item.column() != 0:
            return
        key = self._std_key(item.data(Qt.UserRole) or {})
        if item.checkState() == Qt.Checked:
            if key not in self._std_pick_order:
                self._std_pick_order.append(key)
        elif key in self._std_pick_order:
            self._std_pick_order.remove(key)
        self._refresh_std_summary()

    def _on_std_cell_clicked(self, row, col):
        if col == 0:
            return
        chk = self.std_table.item(row, 0)
        if chk is None:
            return
        chk.setCheckState(Qt.Unchecked if chk.checkState() == Qt.Checked else Qt.Checked)

    def _selected_standards(self):
        self._collect_cond_edits()
        self._collect_eval_edits()
        self._collect_result_edits()
        by_key = {}
        for row in range(self.std_table.rowCount()):
            chk = self.std_table.item(row, 0)
            if chk is None or chk.checkState() != Qt.Checked:
                continue
            data = chk.data(Qt.UserRole) or {}
            by_key[self._std_key(data)] = data
        picked = []
        for key in self._std_pick_order:
            data = by_key.get(key)
            if not data:
                continue
            desc = self._cond_edits.get(key)
            if desc is None:
                desc = _cell_text(data.get("标准描述"))
            eval_req = self._eval_edits.get(key)
            if eval_req is None:
                eval_req = _cell_text(data.get("评价要求"))
            result_desc = self._result_edits.get(key)
            if result_desc is None:
                result_desc = _cell_text(data.get("结果描述"))
            picked.append(TestStandard(
                standard_id=_cell_text(data.get("标准号")),
                chapter=_cell_text(data.get("章节号")),
                test_name=_cell_text(data.get("试验名称")),
                standard_desc=desc,
                result_desc=result_desc,
                evaluation_req=eval_req,
            ))
        return picked

    def _refresh_std_summary(self):
        picked = self._selected_standards()
        if not picked:
            self.drawer_std.set_summary("未选择")
            self.txt_std_method.setText("")
            self._rebuild_cond_drawers([])
            self._rebuild_eval_drawers([])
            self._fill_result_desc_table([])
            return
        refs = [s.ref_label() for s in picked if s.ref_label()]
        preview = "、".join(refs[:4])
        extra = f" 等{len(picked)}项" if len(refs) > 4 else ""
        shown = preview + extra
        self.drawer_std.set_summary(
            f"已选 {len(picked)} 项：{shown}" if shown else f"已选 {len(picked)} 项"
        )
        scratch = TestNode(test_name=self.node_data.test_name or "")
        scratch.apply_standards(picked)
        self.txt_std_method.setText(scratch.joined_test_method())
        self._rebuild_cond_drawers(picked)
        self._rebuild_eval_drawers(picked)
        self._fill_result_desc_table(picked)

    def _collect_map_edits(self, editors, dest):
        for key, editor in list(editors.items()):
            if editor is None:
                continue
            try:
                dest[key] = editor.toPlainText()
            except RuntimeError:
                continue

    def _collect_cond_edits(self):
        self._collect_map_edits(self._cond_editors, self._cond_edits)

    def _collect_eval_edits(self):
        self._collect_map_edits(self._eval_editors, self._eval_edits)

    def _collect_result_edits(self):
        for row in range(self.result_desc_table.rowCount()):
            key_item = self.result_desc_table.item(row, 0)
            key = key_item.data(Qt.UserRole) if key_item else None
            if not key:
                continue
            widget = self.result_desc_table.cellWidget(row, 3)
            if widget is None:
                continue
            try:
                self._result_edits[key] = widget.toPlainText()
            except RuntimeError:
                continue

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_field_drawers(self, layout, picked, edits, get_text, placeholder):
        if not picked:
            self._clear_layout(layout)
            empty = QLabel("未选择标准")
            empty.setObjectName("dimLabel")
            layout.addWidget(empty)
            return [], {}
        drawers = []
        editors = {}
        self._clear_layout(layout)
        for std in picked:
            key = std.identity_key()
            drawer = DrawerSection(std.condition_title())
            drawer.set_expanded(False)
            editor = QTextEdit()
            editor.setMinimumHeight(120)
            editor.setPlaceholderText(placeholder)
            text = edits.get(key)
            if text is None:
                text = get_text(std) or ""
            editor.setPlainText(text)
            drawer.body_layout.addWidget(editor)
            drawer.header.clicked.connect(lambda _=False, d=drawer, bank=drawers: self._accordion(d, bank))
            layout.addWidget(drawer)
            drawers.append(drawer)
            editors[key] = editor
        if len(drawers) == 1:
            drawers[0].set_expanded(True)
        return drawers, editors

    def _accordion(self, opened, bank):
        if not getattr(opened, "_expanded", False):
            return
        for drawer in bank:
            if drawer is not opened:
                drawer.set_expanded(False)

    def _rebuild_cond_drawers(self, picked):
        self._collect_cond_edits()
        self._cond_drawers, self._cond_editors = self._rebuild_field_drawers(
            self.cond_layout,
            picked,
            self._cond_edits,
            lambda s: s.standard_desc,
            "该标准的检测条件，可直接修改",
        )

    def _rebuild_eval_drawers(self, picked):
        self._collect_eval_edits()
        self._eval_drawers, self._eval_editors = self._rebuild_field_drawers(
            self.eval_layout,
            picked,
            self._eval_edits,
            lambda s: s.evaluation_req,
            "该标准的评判要求，可直接修改",
        )

    def _fill_result_desc_table(self, picked):
        self._collect_result_edits()
        self.result_desc_table.setRowCount(0)
        if not picked:
            return
        for std in picked:
            key = std.identity_key()
            row = self.result_desc_table.rowCount()
            self.result_desc_table.insertRow(row)
            id_item = QTableWidgetItem(std.standard_id)
            id_item.setData(Qt.UserRole, key)
            id_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            ch_item = QTableWidgetItem(std.chapter)
            ch_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name_item = QTableWidgetItem(std.test_name)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.result_desc_table.setItem(row, 0, id_item)
            self.result_desc_table.setItem(row, 1, ch_item)
            self.result_desc_table.setItem(row, 2, name_item)
            editor = QTextEdit()
            editor.setFixedHeight(52)
            editor.setPlaceholderText("可直接修改")
            text = self._result_edits.get(key)
            if text is None:
                text = std.result_desc or ""
            editor.setPlainText(text)
            self.result_desc_table.setCellWidget(row, 3, editor)
            self.result_desc_table.setRowHeight(row, 56)
        rows = self.result_desc_table.rowCount()
        self.result_desc_table.setFixedHeight(min(56 * rows + 36, 220) if rows else 80)

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

    def _test_end_date(self):
        if not hasattr(self, "date_end"):
            return QDate()
        end = self.date_end.date()
        return end if end.isValid() else QDate()

    def _refresh_eq_expiry(self):
        if not hasattr(self, "eq_table"):
            return
        end = self._test_end_date()
        self.eq_table.blockSignals(True)
        try:
            for row in range(self.eq_table.rowCount()):
                chk = self.eq_table.item(row, 0)
                data = (chk.data(Qt.UserRole) if chk else None) or {}
                expired = _is_equipment_expired(data.get("计划校准时间"), end)
                name_item = self.eq_table.item(row, 2)
                if name_item is not None:
                    name_item.setData(_EQ_EXPIRED_ROLE, expired)
        finally:
            self.eq_table.blockSignals(False)
        self.eq_table.viewport().update()

    def eventFilter(self, obj, event):
        viewport = self.eq_table.viewport() if hasattr(self, "eq_table") else None
        if obj is viewport:
            etype = event.type()
            if etype == QEvent.MouseMove:
                self._update_eq_expired_tip(event.pos())
            elif etype in (QEvent.Leave, QEvent.HoverLeave, QEvent.Wheel):
                self._hide_eq_expired_tip()
        return super().eventFilter(obj, event)

    def _update_eq_expired_tip(self, pos):
        item = self.eq_table.itemAt(pos)
        if item is None:
            self._hide_eq_expired_tip()
            return
        name_item = self.eq_table.item(item.row(), 2)
        if name_item is None or not name_item.data(_EQ_EXPIRED_ROLE):
            self._hide_eq_expired_tip()
            return
        self._eq_expired_tip.follow(QCursor.pos())

    def _hide_eq_expired_tip(self):
        tip = getattr(self, "_eq_expired_tip", None)
        if tip is not None:
            tip.hide()

    def hideEvent(self, event):
        self._hide_eq_expired_tip()
        super().hideEvent(event)

    def _refresh_eq_summary(self):
        selected = self._selected_equipments()
        if not selected:
            self.drawer_eq.set_summary("未选择")
            return
        preview = "、".join(e.code or e.name for e in selected[:4])
        extra = f" 等{len(selected)}台" if len(selected) > 4 else ""
        self.drawer_eq.set_summary(f"已选 {len(selected)} 台：{preview}{extra}")

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

    def add_sample_row(self, sample_id="", result=TestResult.NA):
        if not isinstance(sample_id, str):
            sample_id = ""
        row = self.table.rowCount()
        self.table.insertRow(row)
        txt_id = QLineEdit(sample_id)
        txt_id.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        txt_id.setStyleSheet("padding: 1px 4px;")
        self.table.setCellWidget(row, 0, txt_id)
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
        self.table.setCellWidget(row, 1, combo_res)
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
        self._restore_standards()
        self._restore_equipments()

        for s in self.node_data.samples:
            self.add_sample_row(s.sample_id, s.result)
        self._refresh_sample_summary()

    def _find_std_row(self, want: TestStandard, used):
        want_key = want.identity_key()
        fallback = None
        for row in range(self.std_table.rowCount()):
            if row in used:
                continue
            chk = self.std_table.item(row, 0)
            data = (chk.data(Qt.UserRole) if chk else None) or {}
            key = self._std_key(data)
            if key == want_key:
                return row
            std_no, chapter, test_name = key
            if want.chapter or want.test_name:
                if (
                    std_no == (want.standard_id or "")
                    and (not want.chapter or chapter == want.chapter)
                    and (not want.test_name or test_name == want.test_name)
                ):
                    return row
            elif std_no == (want.standard_id or "") and fallback is None:
                fallback = row
        return fallback

    def _restore_standards(self):
        wanted = list(self.node_data.standards or [])
        if not wanted:
            wanted = self.node_data.resolved_standards()
        if not wanted:
            self._std_pick_order = []
            self._refresh_std_summary()
            return

        used = set()
        order = []
        self._std_updating = True
        self.std_table.blockSignals(True)
        try:
            for want in wanted:
                row = self._find_std_row(want, used)
                if row is None:
                    continue
                used.add(row)
                chk = self.std_table.item(row, 0)
                if chk is None:
                    continue
                chk.setCheckState(Qt.Checked)
                order.append(self._std_key(chk.data(Qt.UserRole) or {}))
                if len(order) == 1:
                    self.std_table.scrollToItem(chk)
            self._std_pick_order = order
        finally:
            self.std_table.blockSignals(False)
            self._std_updating = False
        for want in wanted:
            key = want.identity_key()
            if want.standard_desc:
                self._cond_edits[key] = want.standard_desc
            if want.evaluation_req:
                self._eval_edits[key] = want.evaluation_req
            if want.result_desc:
                self._result_edits[key] = want.result_desc
        self._refresh_std_summary()

    def _restore_equipments(self):
        saved = list(self.node_data.equipments or [])
        legacy = self.node_data.equipment_name or ""
        self.eq_table.blockSignals(True)
        for row in range(self.eq_table.rowCount()):
            chk = self.eq_table.item(row, 0)
            data = chk.data(Qt.UserRole) if chk else {}
            code = _cell_text((data or {}).get("设备编号"))
            name = _cell_text((data or {}).get("设备名称"))
            checked = equipment_should_restore(code, name, saved, legacy)
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
        self._refresh_eq_expiry()

    def save_and_close(self):
        if self.date_start.date() > self.date_end.date():
            QMessageBox.warning(self, "错误", "开始日期不能晚于结束日期！")
            return

        self.node_data.start_date = self.date_start.date().toString("yyyy-MM-dd")
        self.node_data.end_date = self.date_end.date().toString("yyyy-MM-dd")
        self.node_data.apply_standards(self._selected_standards())

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
                combo_res = self.table.cellWidget(row, 1)
                res = combo_res.currentData()
                samples.append(TestSample(sample_id=txt_id, result=res))
        self.node_data.samples = samples
        self.accept()
