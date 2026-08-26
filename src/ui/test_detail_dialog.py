import math
import re
from datetime import date, datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit, QGroupBox, QMessageBox,
    QTextEdit, QSizePolicy, QAbstractItemView, QScrollArea, QFrame, QWidget,
    QStyledItemDelegate, QStyle, QStyleOptionViewItem, QCheckBox, QInputDialog,
    QDialogButtonBox, QFileDialog,
)
from PySide6.QtCore import Qt, QDate, Signal, QTimer, QEvent, QPoint
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap
from openpyxl.utils import range_boundaries
from src.models.project_state import (
    DataTableRef,
    TestNode,
    TestSample,
    TestResult,
    TestEquipment,
    TestStandard,
)
from src.parsers.key_params import KeyParamReplaceError, apply_key_params, parse_key_params
from src.parsers.db_loader import equipment_display_code, equipment_match_codes
from src.language_copy import format_conclusion
from src.io.data_tables import (
    DataTableError,
    PreviewSnapshot,
    copy_from_template,
    create_blank_workbook,
    delete_attachment,
    import_sample_ids,
    list_data_table_templates,
    open_attachment,
    read_preview_snapshot,
    resolve_attachment_path,
    upload_existing_xlsx,
)
from src.io.test_photos import is_usable_test_name
from src.ui.test_photos_panel import TestPhotosPanel
from src.ui.theme import default_project_qdate, polish_date_edit_calendar
from src.ui.gantt_utils import (
    cascade_subsequent_nodes,
    find_leg_for_node,
    leg_has_overlap,
    node_index_in_leg,
    parse_date,
    restore_leg_dates,
    snapshot_leg_dates,
    would_node_overlap_in_leg,
)

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


def equipment_should_restore(code, name, saved, legacy_name="", match_codes=None):
    """Match a catalog row to saved picks by equipment code, never by shared name."""
    saved = list(saved or [])
    codes = {_cell_text(e.code) for e in saved if _cell_text(getattr(e, "code", ""))}
    candidates = [c for c in ([code] + list(match_codes or [])) if _cell_text(c)]
    if codes:
        return any(c in codes for c in candidates)
    names = {_cell_text(e.name) for e in saved if _cell_text(getattr(e, "name", ""))}
    if names:
        return bool(name) and name in names
    legacy_codes = _legacy_equipment_codes(legacy_name)
    return any(c in legacy_codes for c in candidates)


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


def _pixmap_from_standard_bytes(data: bytes) -> QPixmap:
    """Load standard-library PNG bytes for on-screen preview.

    Library figures are often black line art on a transparent background.
    Compositing onto white keeps ink readable against the dark UI theme.
    """
    pix = QPixmap()
    if not data or not pix.loadFromData(data) or pix.isNull():
        return QPixmap()
    if not pix.hasAlphaChannel():
        return pix
    flat = QPixmap(pix.size())
    flat.fill(QColor("white"))
    painter = QPainter(flat)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    return flat


class StdImagePopup(QLabel):
    """Frameless enlarged image; click to dismiss."""

    def __init__(self, pixmap, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setObjectName("stdImagePopup")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.PointingHandCursor)
        self.setPixmap(pixmap)
        self.adjustSize()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.close()
            event.accept()
            return
        super().mousePressEvent(event)


class StdImageLink(QLabel):
    """Header chip that toggles an enlarged preview of a standard-library image."""

    def __init__(self, text, image_bytes, parent=None):
        super().__init__(text, parent)
        self._bytes = image_bytes
        self._popup = None
        self.setObjectName("stdImageLink")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点击放大，再次点击缩回")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setAttribute(Qt.WA_Hover, True)
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_preview()
            event.accept()
            return
        super().mousePressEvent(event)

    def toggle_preview(self):
        if self._popup is not None:
            self._close_popup()
            return
        pix = _pixmap_from_standard_bytes(self._bytes)
        if pix.isNull():
            return
        host = self.window()
        max_w = max(int((host.width() if host else 800) * 0.75), 240)
        max_h = max(int((host.height() if host else 600) * 0.75), 180)
        if pix.width() > max_w or pix.height() > max_h:
            pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        popup = StdImagePopup(pix, host)
        popup.destroyed.connect(self._on_popup_destroyed)
        self._popup = popup
        if host is not None:
            top_left = host.mapToGlobal(host.rect().center()) - popup.rect().center()
            popup.move(top_left)
        popup.show()
        popup.raise_()

    def _on_popup_destroyed(self, *_args):
        self._popup = None

    def _close_popup(self):
        popup = self._popup
        self._popup = None
        if popup is not None:
            popup.close()

    def hideEvent(self, event):
        self._close_popup()
        super().hideEvent(event)


def _image_link_text(index, total):
    return "图片" if total == 1 else f"图片{index}"


class DrawerSection(QFrame):
    """Collapsible drawer: header stays visible, body toggles."""

    def __init__(self, title, parent=None, wrap_title=False, primary=False):
        super().__init__(parent)
        self.setObjectName("drawerSection")
        self._title = title
        self._expanded = True
        self._wrap_title = wrap_title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = DrawerHeader()
        self.header.setObjectName("drawerHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setAttribute(Qt.WA_Hover, True)
        if wrap_title:
            self.header.setMinimumHeight(36)
        else:
            self.header.setFixedHeight(36)
        head = QHBoxLayout(self.header)
        head.setContentsMargins(12, 6, 12, 6)
        head.setSpacing(8)
        if wrap_title:
            head.setAlignment(Qt.AlignTop)
        self.header_layout = head
        self.lbl_arrow = QLabel("▼")
        self.lbl_arrow.setObjectName("drawerArrowPrimary" if primary else "drawerArrow")
        self.lbl_arrow.setFixedWidth(14)
        if wrap_title:
            self.lbl_title = QLabel(title)
            self.lbl_title.setWordWrap(True)
            self.lbl_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        else:
            self.lbl_title = ElidedLabel(title)
        self.lbl_title.setObjectName("drawerTitlePrimary" if primary else "drawerTitle")
        self.lbl_summary = ElidedLabel("")
        self.lbl_summary.setObjectName("dimLabel")
        self.lbl_summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.image_host = QWidget()
        self.image_host.setObjectName("stdImageHost")
        self.image_layout = QHBoxLayout(self.image_host)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_layout.setSpacing(8)
        self.image_host.setVisible(False)
        head.addWidget(self.lbl_arrow, 0, Qt.AlignTop)
        head.addWidget(self.lbl_title, stretch=1)
        self.lbl_summary.hide()
        head.addWidget(self.lbl_summary, stretch=0 if wrap_title else 2)
        head.addWidget(self.image_host, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.header.clicked.connect(self.toggle)
        root.addWidget(self.header)

        self.accessory = QWidget()
        self.accessory.setObjectName("drawerAccessory")
        self.accessory_layout = QHBoxLayout(self.accessory)
        self.accessory_layout.setContentsMargins(12, 2, 12, 6)
        self.accessory_layout.setSpacing(8)
        self.accessory.hide()
        root.addWidget(self.accessory)

        self.body = QWidget()
        self.body.setObjectName("drawerBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 6, 10, 10)
        self.body_layout.setSpacing(6)
        root.addWidget(self.body)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def set_summary(self, text, tooltip=None):
        summary = text or ""
        self.lbl_summary.setText(summary)
        if tooltip is not None:
            self.lbl_summary.setToolTip(tooltip)
        self.lbl_summary.setVisible(bool(summary))

    def set_images(self, images):
        while self.image_layout.count():
            item = self.image_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        blobs = [b for b in (images or []) if b]
        self.image_host.setVisible(bool(blobs))
        total = len(blobs)
        for i, blob in enumerate(blobs, start=1):
            self.image_layout.addWidget(
                StdImageLink(_image_link_text(i, total), blob, self.image_host)
            )

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
        elif self._wrap_title:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        else:
            self.setFixedHeight(max(self.header.height(), 36))
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
        self._std_images = {}
        self._cond_edits = {}
        self._cond_edits_en = {}
        self._cond_editors = {}
        self._cond_drawers = []
        self._key_param_edits = {}
        self._key_param_defaults = {}
        self._key_param_confirmed = {}
        self._key_param_library = {}
        self._key_param_library_en = {}
        self._key_param_rows = {}
        self._key_param_updating = False
        self._eval_edits = {}
        self._eval_edits_en = {}
        self._eval_editors = {}
        self._eval_drawers = []
        self._result_edits = {}
        self._result_edits_en = {}
        self._data_tables = [
            DataTableRef(title=r.title, relative_path=r.relative_path)
            for r in (node_data.data_tables or [])
        ]
        self._data_table_drawers = []
        self._data_table_preview_cache = {}
        self._data_table_preview_tables = {}

        self.proj_start_date = None
        self.proj_end_date = None
        self._project_state = None
        self._prev_node_end = None  # QDate | None — end of the preceding node in the same Leg

        p = self.parent()
        while p and not hasattr(p, "state"):
            p = p.parent()
        if p and hasattr(p, "state"):
            self._project_state = p.state
            try:
                if p.state.test_start_date:
                    start = QDate.fromString(p.state.test_start_date, "yyyy-MM-dd")
                    if start.isValid() and start.year() >= 1990:
                        self.proj_start_date = start
                if p.state.test_end_date:
                    end = QDate.fromString(p.state.test_end_date, "yyyy-MM-dd")
                    if end.isValid() and end.year() >= 1990:
                        self.proj_end_date = end
            except Exception:
                pass
            self._prev_node_end = self._compute_prev_end(p.state, node_data)

        self.setWindowTitle(f"编辑明细 - {node_data.test_name}")
        self.resize(860, 760)
        self.setMinimumSize(680, 560)

        self.init_ui()
        self.load_data()

    def _edit_lang(self) -> str:
        state = self._project_state
        if state is not None and hasattr(state, "_edit_lang"):
            return state._edit_lang()
        return "中文"

    def _is_edit_en(self) -> bool:
        return self._edit_lang() == "英文"

    def _active_cond_edits(self):
        return self._cond_edits_en if self._is_edit_en() else self._cond_edits

    def _active_eval_edits(self):
        return self._eval_edits_en if self._is_edit_en() else self._eval_edits

    def _active_result_edits(self):
        return self._result_edits_en if self._is_edit_en() else self._result_edits

    def _result_display(self, result: TestResult) -> str:
        return format_conclusion(result, self._edit_lang())

    def _make_calendar_date_edit(self):
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setMinimumDate(QDate(1990, 1, 1))
        date_edit.setMaximumDate(QDate(9999, 12, 31))
        date_edit.setDate(default_project_qdate())
        date_edit.lineEdit().setReadOnly(True)
        calendar = date_edit.calendarWidget()
        if calendar is not None:
            calendar.setMinimumDate(QDate(1990, 1, 1))
            calendar.setMaximumDate(QDate(9999, 12, 31))
        polish_date_edit_calendar(date_edit)
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
            self._forget_all_key_params()
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

        self.drawer_std = DrawerSection("测试标准", primary=True)
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
            ["试验名称", "结果描述"], 160
        )
        self.result_desc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.result_desc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        std_layout.addWidget(self.result_desc_table)
        layout.addWidget(self.drawer_std)

        self.drawer_eq = DrawerSection("测试设备", primary=True)
        eq_layout = self.drawer_eq.body_layout
        eq_layout.addWidget(QLabel("可多选，点击行或勾选"))

        self.txt_eq_search = QLineEdit()
        self.txt_eq_search.setPlaceholderText("搜索设备编号或设备名称，如 TTE、温湿度")
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

        self.drawer_sample = DrawerSection("样品与结果", primary=True)
        sample_layout = self.drawer_sample.body_layout
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.btn_import_from_prev = QPushButton("从前置试验导入")
        self.btn_import_from_prev.clicked.connect(self._import_from_preceding_test)
        toolbar.addWidget(self.btn_import_from_prev)

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
        self.txt_sample_start.setFixedWidth(144)
        toolbar.addWidget(self.txt_sample_start)

        toolbar.addWidget(QLabel("数量"))
        self.txt_sample_qty = QLineEdit()
        self.txt_sample_qty.setPlaceholderText("3")
        self.txt_sample_qty.setText("3")
        self.txt_sample_qty.setFixedWidth(40)
        toolbar.addWidget(self.txt_sample_qty)

        self.btn_gen_samples = QPushButton("生成编号列")
        self.btn_gen_samples.setObjectName("accentButton")
        self.btn_gen_samples.setToolTip("按首字母+起始号+数量生成样品，已存在的编号会跳过")
        self.btn_gen_samples.clicked.connect(self._generate_samples)
        toolbar.addWidget(self.btn_gen_samples)

        self.btn_add_appno = QPushButton("添加单号")
        self.btn_add_appno.setToolTip("在已有样品号前加上申请单号，已加过的不会重复加")
        self.btn_add_appno.clicked.connect(self._prepend_application_no)
        toolbar.addWidget(self.btn_add_appno)

        self.btn_add_data_table = QPushButton("添加数据表")
        self.btn_add_data_table.setToolTip("上传 Excel / 自由编辑 / 模版")
        self.btn_add_data_table.clicked.connect(self._on_add_data_table)
        toolbar.addWidget(self.btn_add_data_table)
        toolbar.addStretch()
        sample_layout.addLayout(toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "样品编号", "结果描述", "测试结果"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setMinimumHeight(32)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setColumnWidth(0, 28)
        self.table.setColumnWidth(1, 158)
        self.table.setColumnWidth(3, 168)
        self.table.setMinimumHeight(400)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sample_layout.addWidget(self.table)
        self._setup_result_header()
        self._sample_add_header_btn = self._install_sample_add_header_button()

        sample_layout.addWidget(QLabel("数据表"))
        self.data_table_host = QWidget()
        self.data_table_layout = QVBoxLayout(self.data_table_host)
        self.data_table_layout.setContentsMargins(0, 0, 0, 0)
        self.data_table_layout.setSpacing(4)
        sample_layout.addWidget(self.data_table_host)
        layout.addWidget(self.drawer_sample)

        self.drawer_photos = DrawerSection("试验照片", primary=True)
        project_root = None
        project_id = ""
        if self._project_state is not None:
            raw = getattr(self._project_state, "project_path", "") or ""
            if raw:
                project_root = Path(raw)
            project_id = getattr(self._project_state, "project_id", "") or ""
        self.photos_panel = TestPhotosPanel(
            project_root, self.node_data.test_name, project_id, self.drawer_photos
        )
        self.photos_panel.changed.connect(self._refresh_photo_summary)
        self.drawer_photos.body_layout.addWidget(self.photos_panel)
        layout.addWidget(self.drawer_photos)
        layout.addStretch(1)

        self.drawer_std.set_expanded(True)
        self.drawer_eq.set_expanded(False)
        self.drawer_sample.set_expanded(False)
        self.drawer_photos.set_expanded(False)
        self._refresh_photo_summary()

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
        self._refresh_import_from_prev_button()

    def _install_sample_add_header_button(self):
        header = self.table.horizontalHeader()
        btn = QPushButton("↓", header.viewport())
        btn.setObjectName("headerAddRowButton")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setToolTip("添加样品行")
        btn.clicked.connect(lambda: self.add_sample_row())

        def sync(*_args, b=btn):
            self._sync_sample_add_header_button(b)

        header.sectionResized.connect(sync)
        header.geometriesChanged.connect(sync)
        self.table.horizontalScrollBar().valueChanged.connect(sync)
        QTimer.singleShot(0, sync)
        return btn

    def _sync_sample_add_header_button(self, btn):
        header = self.table.horizontalHeader()
        x = header.sectionViewportPosition(0)
        w = header.sectionSize(0)
        h = header.height()
        size = min(18, max(w - 6, 12), max(h - 8, 12))
        btn.setGeometry(x + max((w - size) // 2, 1), max((h - size) // 2, 1), size, size)
        btn.raise_()

    def _setup_result_header(self):
        header = self.table.horizontalHeader()
        self._header_sync_pending = False
        self.combo_bulk_result = QComboBox(header.viewport())
        self.combo_bulk_result.setObjectName("bulkResultCombo")
        self.combo_bulk_result.setFocusPolicy(Qt.StrongFocus)
        self.combo_bulk_result.addItem("—")
        for r in TestResult:
            self.combo_bulk_result.addItem(self._result_display(r), userData=r)
        self._expand_result_combo_popup(self.combo_bulk_result)
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

    def _expand_result_combo_popup(self, combo):
        """Keep Pass/Fail/N/A (and the bulk '—') all visible without scrolling."""
        count = combo.count()
        combo.setMaxVisibleItems(max(count, 4))
        view = combo.view()
        if view is not None:
            view.setMinimumHeight(22 * count)

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
        x = header.sectionViewportPosition(3)
        section_w = header.sectionSize(3)
        combo_w = 86
        combo_h = 24
        left_pad = 8
        gap = 6
        right_margin = 12
        label = header.model().headerData(3, Qt.Horizontal) or "测试结果"
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
        if hasattr(self, "_sample_add_header_btn"):
            self._sync_sample_add_header_button(self._sample_add_header_btn)

    def _apply_bulk_result(self, index):
        data = self.combo_bulk_result.itemData(index) if index >= 0 else None
        text = self.combo_bulk_result.itemText(index) if index >= 0 else self.combo_bulk_result.currentText()
        if text in ("", "—") and data is None:
            return
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 3)
            if combo is None:
                continue
            if data is not None:
                pos = combo.findData(data)
            else:
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
        use_en = self._is_edit_en()
        for eq in self.equipments:
            code = equipment_display_code(eq)
            name_cn = _cell_text(eq.get("设备名称"))
            name_en = _cell_text(eq.get("Equipment"))
            name = name_en if use_en else name_cn
            model = _cell_text(eq.get("型号"))
            cal = _format_cal_date(eq.get("计划校准时间"))
            if not (code or name_cn or name_en):
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
    def _std_ref_key(std):
        if isinstance(std, TestStandard):
            return std.ref_key()
        return (
            _cell_text((std or {}).get("标准号")),
            _cell_text((std or {}).get("章节号")),
        )

    def _on_std_item_changed(self, item):
        if self._std_updating or item is None or item.column() != 0:
            return
        key = self._std_ref_key(item.data(Qt.UserRole) or {})
        if item.checkState() == Qt.Checked:
            if key not in self._std_pick_order:
                self._std_pick_order.append(key)
        elif key in self._std_pick_order:
            # Keep in-session edits / key-param confirm so uncheck→recheck
            # restores the same state (and the detail-complete mark stays).
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
        self._collect_key_param_edits()
        by_key = {}
        for row in range(self.std_table.rowCount()):
            chk = self.std_table.item(row, 0)
            if chk is None or chk.checkState() != Qt.Checked:
                continue
            data = chk.data(Qt.UserRole) or {}
            by_key[self._std_ref_key(data)] = data
        picked = []
        for key in self._std_pick_order:
            data = by_key.get(key)
            if not data:
                continue
            self._ensure_key_param_state(key, data)
            desc = self._cond_edits.get(key)
            if desc is None:
                desc = _cell_text(data.get("标准描述"))
            desc_en = self._cond_edits_en.get(key)
            if desc_en is None:
                desc_en = _cell_text(data.get("condition"))
            eval_req = self._eval_edits.get(key)
            if eval_req is None:
                eval_req = _cell_text(data.get("评价要求"))
            eval_req_en = self._eval_edits_en.get(key)
            if eval_req_en is None:
                eval_req_en = _cell_text(data.get("Evaluation requirement"))
            result_desc = self._result_edits.get(key)
            if result_desc is None:
                result_desc = _cell_text(data.get("结果描述"))
            result_desc_en = self._result_edits_en.get(key)
            if result_desc_en is None:
                result_desc_en = _cell_text(data.get("result"))
            images = self._std_images.get(key)
            if images is None:
                images = list(data.get("_images") or [])
            picked.append(TestStandard(
                standard_id=_cell_text(data.get("标准号")),
                chapter=_cell_text(data.get("章节号")),
                test_name=_cell_text(data.get("试验名称")),
                test_item=_cell_text(data.get("test item")),
                standard_desc=desc,
                standard_desc_en=desc_en,
                result_desc=result_desc,
                result_desc_en=result_desc_en,
                evaluation_req=eval_req,
                evaluation_req_en=eval_req_en,
                images=list(images or []),
                key_params=list(self._key_param_edits.get(key) or []),
                key_params_defaults=list(self._key_param_defaults.get(key) or []),
                key_params_confirmed=bool(self._key_param_confirmed.get(key)),
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
            self._apply_result_desc_to_rows("")
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
        self._apply_result_desc_to_rows(self._current_result_desc())

    def _collect_map_edits(self, editors, dest):
        for key, editor in list(editors.items()):
            if editor is None:
                continue
            try:
                dest[key] = editor.toPlainText()
            except RuntimeError:
                continue

    def _collect_cond_edits(self):
        # Do not prune by pick order: unchecked standards may be re-checked
        # in the same dialog session and should keep their edited text.
        self._collect_map_edits(self._cond_editors, self._active_cond_edits())

    def _collect_key_param_edits(self):
        allowed = set(self._std_pick_order)
        for key, row in list(self._key_param_rows.items()):
            if key not in allowed:
                continue
            edits = row.get("edits") or []
            values = []
            alive = False
            for edit in edits:
                try:
                    values.append(edit.text().strip())
                    alive = True
                except RuntimeError:
                    continue
            if alive:
                self._key_param_edits[key] = values
            chk = row.get("check")
            if chk is None:
                continue
            try:
                self._key_param_confirmed[key] = chk.isChecked()
            except RuntimeError:
                continue

    def _ensure_key_param_state(self, key, data):
        library = _cell_text(data.get("标准描述"))
        library_en = _cell_text(data.get("condition"))
        self._key_param_library[key] = library
        self._key_param_library_en[key] = library_en
        if key not in self._key_param_defaults:
            self._key_param_defaults[key] = parse_key_params(data.get("关键参数"))
        if key not in self._key_param_edits:
            self._key_param_edits[key] = list(self._key_param_defaults[key])
        if key not in self._key_param_confirmed:
            self._key_param_confirmed[key] = False
        if key not in self._cond_edits and library:
            self._cond_edits[key] = library
        if key not in self._cond_edits_en and library_en:
            self._cond_edits_en[key] = library_en

    def _forget_key_params(self, key):
        self._key_param_edits.pop(key, None)
        self._key_param_defaults.pop(key, None)
        self._key_param_confirmed.pop(key, None)
        self._key_param_library.pop(key, None)
        self._key_param_library_en.pop(key, None)
        self._key_param_rows.pop(key, None)
        self._cond_edits.pop(key, None)
        self._cond_edits_en.pop(key, None)

    def _forget_all_key_params(self):
        self._key_param_edits.clear()
        self._key_param_defaults.clear()
        self._key_param_confirmed.clear()
        self._key_param_library.clear()
        self._key_param_library_en.clear()
        self._key_param_rows.clear()
        self._cond_edits.clear()
        self._cond_edits_en.clear()

    def _collect_eval_edits(self):
        self._collect_map_edits(self._eval_editors, self._active_eval_edits())

    def _collect_result_edits(self):
        dest = self._active_result_edits()
        for row in range(self.result_desc_table.rowCount()):
            key_item = self.result_desc_table.item(row, 0)
            key = key_item.data(Qt.UserRole) if key_item else None
            if not key:
                continue
            widget = self.result_desc_table.cellWidget(row, 1)
            if widget is None:
                continue
            try:
                dest[key] = widget.toPlainText()
            except RuntimeError:
                continue

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _catalog_images(self, std):
        key = self._std_ref_key(std)
        saved = self._std_images.get(key)
        if saved:
            return list(saved)
        if getattr(std, "images", None):
            return list(std.images)
        for rec in self.standards:
            if self._std_ref_key(rec) == key:
                return list(rec.get("_images") or [])
        return []

    def _rebuild_field_drawers(self, layout, picked, edits, get_text, placeholder, image_getter=None):
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
            key = self._std_ref_key(std)
            drawer = DrawerSection(std.field_title(), wrap_title=True)
            drawer.set_expanded(False)
            if image_getter is not None:
                drawer.set_images(image_getter(std))
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
        self._collect_key_param_edits()
        active = self._active_cond_edits()
        self._cond_drawers, self._cond_editors = self._rebuild_field_drawers(
            self.cond_layout,
            picked,
            active,
            lambda s: (s.standard_desc_en if self._is_edit_en() else s.standard_desc),
            "该标准的检测条件，可直接修改",
            image_getter=self._catalog_images,
        )
        self._key_param_rows = {}
        for std, drawer in zip(picked, self._cond_drawers):
            self._attach_key_param_row(drawer, std)

    def _attach_key_param_row(self, drawer, std):
        layout = drawer.accessory_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        key = self._std_ref_key(std)
        defaults = list(self._key_param_defaults.get(key) or std.key_params_defaults or [])
        if not defaults:
            drawer.accessory.hide()
            return
        values = list(self._key_param_edits.get(key) or defaults)
        if len(values) < len(defaults):
            values = values + defaults[len(values):]
        confirmed = bool(self._key_param_confirmed.get(key))

        lbl = QLabel("关键参数：")
        lbl.setObjectName("keyParamLabel")
        layout.addWidget(lbl)

        edits = []
        self._key_param_updating = True
        try:
            for index, default in enumerate(defaults):
                edit = QLineEdit()
                edit.setObjectName("keyParamEdit")
                edit.setText(values[index] if index < len(values) else default)
                edit.setMinimumWidth(120)
                edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                edit.textChanged.connect(lambda _text, k=key: self._on_key_param_text_changed(k))
                layout.addWidget(edit, stretch=1)
                edits.append(edit)
            chk = QCheckBox()
            chk.setObjectName("keyParamCheck")
            chk.setToolTip("确认后将关键参数代入下方检测条件")
            chk.setChecked(confirmed)
            chk.toggled.connect(lambda checked, k=key: self._on_key_param_toggled(k, checked))
            layout.addWidget(chk)
            ok = QLabel("参数已确认")
            ok.setObjectName("keyParamConfirmed")
            ok.setVisible(confirmed)
            layout.addWidget(ok)
        finally:
            self._key_param_updating = False
        layout.addStretch(0)
        drawer.accessory.show()
        self._key_param_rows[key] = {"edits": edits, "check": chk, "ok": ok}

    def _on_key_param_text_changed(self, key):
        if self._key_param_updating:
            return
        row = self._key_param_rows.get(key) or {}
        chk = row.get("check")
        if chk is None or not chk.isChecked():
            return
        chk.setChecked(False)

    def _on_key_param_toggled(self, key, checked):
        if self._key_param_updating:
            return
        row = self._key_param_rows.get(key) or {}
        chk = row.get("check")
        ok = row.get("ok")
        editor = self._cond_editors.get(key)
        library = self._key_param_library.get(key, "")
        library_en = self._key_param_library_en.get(key, "")
        if checked:
            values = []
            for edit in row.get("edits") or []:
                try:
                    values.append(edit.text().strip())
                except RuntimeError:
                    values.append("")
            defaults = list(self._key_param_defaults.get(key) or [])
            try:
                text_cn = apply_key_params(library, defaults, values) if library else ""
            except KeyParamReplaceError as exc:
                QMessageBox.warning(self, "提示", str(exc))
                self._key_param_updating = True
                try:
                    if chk is not None:
                        chk.setChecked(False)
                    if ok is not None:
                        ok.setVisible(False)
                finally:
                    self._key_param_updating = False
                self._key_param_confirmed[key] = False
                return
            if library_en:
                try:
                    text_en = apply_key_params(library_en, defaults, values)
                except KeyParamReplaceError:
                    text_en = library_en
            else:
                text_en = ""
            if library:
                self._cond_edits[key] = text_cn
            if library_en:
                self._cond_edits_en[key] = text_en
            show = text_en if self._is_edit_en() else text_cn
            if editor is not None:
                editor.setPlainText(show)
            self._key_param_edits[key] = values
            self._key_param_confirmed[key] = True
            if ok is not None:
                ok.setVisible(True)
            return
        self._cond_edits[key] = library
        self._cond_edits_en[key] = library_en
        restore = library_en if self._is_edit_en() else library
        if editor is not None:
            editor.setPlainText(restore)
        self._key_param_confirmed[key] = False
        if ok is not None:
            ok.setVisible(False)

    def _rebuild_eval_drawers(self, picked):
        self._collect_eval_edits()
        self._eval_drawers, self._eval_editors = self._rebuild_field_drawers(
            self.eval_layout,
            picked,
            self._active_eval_edits(),
            lambda s: (s.evaluation_req_en if self._is_edit_en() else s.evaluation_req),
            "该标准的评判要求，可直接修改",
        )

    def _fill_result_desc_table(self, picked):
        self._collect_result_edits()
        self.result_desc_table.setRowCount(0)
        if not picked:
            return
        active = self._active_result_edits()
        for std in picked:
            key = self._std_ref_key(std)
            row = self.result_desc_table.rowCount()
            self.result_desc_table.insertRow(row)
            name_item = QTableWidgetItem(std.test_name)
            name_item.setData(Qt.UserRole, key)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.result_desc_table.setItem(row, 0, name_item)
            editor = QTextEdit()
            editor.setFixedHeight(52)
            editor.setPlaceholderText("可直接修改")
            text = active.get(key)
            if text is None:
                text = (
                    std.result_desc_en if self._is_edit_en() else std.result_desc
                ) or ""
            editor.setPlainText(text)
            self.result_desc_table.setCellWidget(row, 1, editor)
            editor.textChanged.connect(self._on_result_desc_edited)
            self.result_desc_table.setRowHeight(row, 56)
        rows = self.result_desc_table.rowCount()
        self.result_desc_table.setFixedHeight(min(56 * rows + 36, 220) if rows else 80)

    def _on_result_desc_edited(self):
        self._apply_result_desc_to_rows(self._current_result_desc())

    def _current_result_desc(self):
        """Joined text from the editable 结果描述 table (selection order)."""
        self._collect_result_edits()
        active = self._active_result_edits()
        parts = []
        if hasattr(self, "result_desc_table"):
            for row in range(self.result_desc_table.rowCount()):
                key_item = self.result_desc_table.item(row, 0)
                key = key_item.data(Qt.UserRole) if key_item else None
                widget = self.result_desc_table.cellWidget(row, 1)
                text = ""
                if widget is not None:
                    try:
                        text = widget.toPlainText().strip()
                    except RuntimeError:
                        text = ""
                if not text and key is not None:
                    text = (active.get(key) or "").strip()
                if text:
                    parts.append(text)
        if parts:
            return "\n\n".join(parts)
        for std in self.node_data.resolved_standards():
            text = (
                (std.result_desc_en if self._is_edit_en() else std.result_desc) or ""
            ).strip()
            if text:
                parts.append(text)
        if parts:
            return "\n\n".join(parts)
        attr = "result_desc_en" if self._is_edit_en() else "result_desc"
        return _cell_text(getattr(self.node_data, attr, None))

    def _apply_result_desc_to_rows(self, text):
        text = text or ""
        if not hasattr(self, "table"):
            return
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 2)
            if widget is not None:
                widget.setText(text)
                widget.setCursorPosition(0)

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
        labels = []
        for e in selected:
            disp_name = e.name_en if self._is_edit_en() else e.name
            parts = [p for p in (e.code, disp_name) if p and str(p).strip()]
            if e.model and str(e.model).strip():
                parts.append(f"({e.model})")
            labels.append(" ".join(parts) if parts else "/")
        preview = "、".join(
            (e.code or (e.name_en if self._is_edit_en() else e.name) or "/")
            for e in selected[:4]
        )
        extra = f" 等{len(selected)}台" if len(selected) > 4 else ""
        summary = f"已选 {len(selected)} 台：{preview}{extra}"
        self.drawer_eq.set_summary(summary, tooltip="\n".join(labels))

    def _selected_equipments(self):
        picked = []
        for row in range(self.eq_table.rowCount()):
            chk = self.eq_table.item(row, 0)
            if chk is None or chk.checkState() != Qt.Checked:
                continue
            data = chk.data(Qt.UserRole) or {}
            code_item = self.eq_table.item(row, 1)
            cal_item = self.eq_table.item(row, 4)
            picked.append(TestEquipment(
                name=_cell_text(data.get("设备名称")),
                name_en=_cell_text(data.get("Equipment")),
                code=(code_item.text().strip() if code_item else "")
                or equipment_display_code(data),
                model=_cell_text(data.get("型号")),
                valid_date=(cal_item.text().strip() if cal_item else "")
                or _format_cal_date(data.get("计划校准时间")),
            ))
        return picked

    def add_sample_row(self, sample_id="", result=TestResult.NA, result_desc=None):
        if not isinstance(sample_id, str):
            sample_id = ""
        row = self.table.rowCount()
        self.table.insertRow(row)

        del_wrap = QWidget()
        del_lay = QHBoxLayout(del_wrap)
        del_lay.setContentsMargins(0, 0, 0, 0)
        del_lay.setAlignment(Qt.AlignCenter)
        btn_del = QPushButton("✕")
        btn_del.setObjectName("fieldRemoveButton")
        btn_del.setFixedSize(20, 20)
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setFocusPolicy(Qt.NoFocus)
        btn_del.setToolTip("删除此行")
        btn_del.clicked.connect(self._remove_sample_row)
        del_lay.addWidget(btn_del)
        self.table.setCellWidget(row, 0, del_wrap)

        txt_id = QLineEdit(sample_id)
        txt_id.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        txt_id.setStyleSheet("padding: 1px 4px;")
        self.table.setCellWidget(row, 1, txt_id)

        txt_desc = QLineEdit(
            result_desc if result_desc is not None else self._current_result_desc()
        )
        txt_desc.setReadOnly(True)
        txt_desc.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        txt_desc.setStyleSheet("padding: 1px 4px;")
        txt_desc.setPlaceholderText("选择标准后自动填入")
        txt_desc.setCursorPosition(0)
        self.table.setCellWidget(row, 2, txt_desc)

        combo_res = QComboBox()
        for r in TestResult:
            combo_res.addItem(self._result_display(r), userData=r)
        self._expand_result_combo_popup(combo_res)
        bulk_data = None
        if hasattr(self, "combo_bulk_result"):
            bulk_data = self.combo_bulk_result.currentData()
        if isinstance(bulk_data, TestResult):
            combo_res.setCurrentIndex(combo_res.findData(bulk_data))
        else:
            combo_res.setCurrentIndex(combo_res.findData(result))
        self.table.setCellWidget(row, 3, combo_res)
        self._refresh_sample_summary()
        self._schedule_result_header_sync()

    def _remove_sample_row(self):
        btn = self.sender()
        if btn is None:
            return
        for row in range(self.table.rowCount()):
            wrap = self.table.cellWidget(row, 0)
            if wrap is None:
                continue
            if wrap is btn or wrap.findChild(QPushButton) is btn:
                self.table.removeRow(row)
                self._refresh_sample_summary()
                self._schedule_result_header_sync()
                return

    def _existing_sample_ids(self):
        ids = []
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 1)
            if widget is None:
                continue
            text = widget.text().strip()
            if text:
                ids.append(text)
        return ids

    def _preceding_node_in_leg(self):
        state = self._project_state
        if state is None:
            return None
        leg = find_leg_for_node(state, self.node_data)
        if leg is None:
            return None
        idx = node_index_in_leg(leg, self.node_data)
        if idx <= 0:
            return None
        return leg.nodes[idx - 1]

    def _refresh_import_from_prev_button(self):
        if not hasattr(self, "btn_import_from_prev"):
            return
        prev = self._preceding_node_in_leg()
        self.btn_import_from_prev.setEnabled(prev is not None)
        if prev is not None:
            name = (prev.test_name or "").strip() or "前置试验"
            self.btn_import_from_prev.setToolTip(
                f"从「{name}」复制样品编号（已存在的编号与测试结果不会改动）"
            )
        else:
            self.btn_import_from_prev.setToolTip("当前是本 Leg 第一条试验，没有可导入的前置试验")

    def _import_from_preceding_test(self):
        prev = self._preceding_node_in_leg()
        if prev is None:
            QMessageBox.information(self, "提示", "当前是本 Leg 第一条试验，没有可导入的前置试验。")
            return

        ids = []
        for sample in prev.samples or []:
            sid = (sample.sample_id or "").strip()
            if sid:
                ids.append(sid)
        if not ids:
            name = (prev.test_name or "").strip() or "前置试验"
            QMessageBox.information(self, "提示", f"前置试验「{name}」没有样品编号可导入。")
            return

        existing = set(self._existing_sample_ids())
        added = 0
        for sid in ids:
            if sid in existing:
                continue
            self.add_sample_row(sid)
            existing.add(sid)
            added += 1
        if added == 0:
            QMessageBox.information(self, "提示", "前置试验的样品编号已全部存在，未重复导入。")

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
            widget = self.table.cellWidget(row, 1)
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

    def _refresh_photo_summary(self):
        if not hasattr(self, "photos_panel"):
            return
        albums, photos = self.photos_panel.counts()
        if albums == 0:
            self.drawer_photos.set_summary("未添加")
        else:
            self.drawer_photos.set_summary(f"{albums} 夹 / {photos} 张")

    def load_data(self):
        if self.node_data.start_date:
            self.date_start.setDate(QDate.fromString(self.node_data.start_date, "yyyy-MM-dd"))
        else:
            self.date_start.setDate(default_project_qdate())

        if self.node_data.end_date:
            self.date_end.setDate(QDate.fromString(self.node_data.end_date, "yyyy-MM-dd"))
        else:
            self.date_end.setDate(default_project_qdate())

        lo = self._start_lower_bound()
        _, hi = self._project_date_bounds()
        self._apply_node_date_limits(lo, lo, hi)

        # Clamp current value if it violates the predecessor constraint
        if self.date_start.date() < lo:
            self.date_start.setDate(lo)

        self._on_node_dates_changed()
        self._restore_standards()
        self._restore_equipments()

        for s in self.node_data.samples:
            self.add_sample_row(s.sample_id, s.result)
        self._apply_result_desc_to_rows(self._current_result_desc())
        self._refresh_sample_summary()
        self._refresh_data_table_list()
        self._sync_data_table_button()

    def _project_root(self):
        raw = ""
        if self._project_state is not None:
            raw = getattr(self._project_state, "project_path", "") or ""
        return Path(raw) if raw else None

    def _sync_data_table_button(self):
        ok = is_usable_test_name(self.node_data.test_name) and self._project_root() is not None
        self.btn_add_data_table.setEnabled(ok)
        if not is_usable_test_name(self.node_data.test_name):
            self.btn_add_data_table.setToolTip("请先选择试验名称")
        elif self._project_root() is None:
            self.btn_add_data_table.setToolTip("请先加载项目以确定本地镜像路径")
        else:
            self.btn_add_data_table.setToolTip("上传 Excel / 自由编辑 / 模版")

    def _clear_data_table_drawers(self):
        while self.data_table_layout.count():
            item = self.data_table_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._data_table_drawers = []
        self._data_table_preview_tables = {}

    def _load_preview_for_ref(self, ref: DataTableRef, force: bool = False) -> PreviewSnapshot:
        key = ref.relative_path
        if not force and key in self._data_table_preview_cache:
            return self._data_table_preview_cache[key]
        root = self._project_root()
        if root is None:
            snap = PreviewSnapshot(sheet_name="", values=[], merges=[])
            self._data_table_preview_cache[key] = snap
            return snap
        path = resolve_attachment_path(root, ref)
        try:
            snap = read_preview_snapshot(path)
        except DataTableError:
            snap = PreviewSnapshot(sheet_name="", values=[], merges=[])
        self._data_table_preview_cache[key] = snap
        return snap

    def _fill_preview_table(self, table: QTableWidget, snap: PreviewSnapshot):
        table.clearSpans()
        table.clear()
        rows = snap.values or []
        cols = max((len(r) for r in rows), default=0)
        table.setRowCount(len(rows))
        table.setColumnCount(cols)
        table.setHorizontalHeaderLabels([str(i + 1) for i in range(cols)])
        table.verticalHeader().setVisible(True)
        for r, row in enumerate(rows):
            for c in range(cols):
                text = row[c] if c < len(row) else ""
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(r, c, item)
        origin_r = snap.origin_row or 1
        origin_c = snap.origin_col or 1
        for merge in snap.merges or []:
            try:
                min_c, min_r, max_c, max_r = range_boundaries(merge)
            except Exception:
                continue
            r0 = min_r - origin_r
            c0 = min_c - origin_c
            r1 = max_r - origin_r
            c1 = max_c - origin_c
            if r0 < 0 or c0 < 0 or r1 >= len(rows) or c1 >= cols:
                continue
            row_span = r1 - r0 + 1
            col_span = c1 - c0 + 1
            if row_span > 1 or col_span > 1:
                table.setSpan(r0, c0, row_span, col_span)
        table.resizeColumnsToContents()

    def _refresh_data_table_list(self):
        keep = {ref.relative_path for ref in self._data_tables}
        self._data_table_preview_cache = {
            k: v for k, v in self._data_table_preview_cache.items() if k in keep
        }
        self._clear_data_table_drawers()
        if not self._data_tables:
            empty = QLabel("尚未添加数据表")
            empty.setObjectName("dimLabel")
            self.data_table_layout.addWidget(empty)
            return
        for ref in self._data_tables:
            drawer = DrawerSection(ref.title, wrap_title=True)
            drawer._data_table_rel = ref.relative_path
            drawer.set_expanded(False)
            bar = QHBoxLayout()
            bar.addStretch()
            btn_import = QPushButton("导入样品编号")
            btn_import.setToolTip("从当前样品表写入本表第 1 列（有内容则左插一列），从第 2 行起")
            btn_import.clicked.connect(
                lambda _=False, r=ref: self._import_sample_ids_to_data_table(r)
            )
            bar.addWidget(btn_import)
            btn_open = QPushButton("打开编辑")
            btn_open.setToolTip("用本机 Excel / WPS / 系统默认程序打开")
            btn_open.clicked.connect(lambda _=False, r=ref: self._open_data_table(r))
            bar.addWidget(btn_open)
            btn_refresh = QPushButton("刷新")
            btn_refresh.setToolTip("从磁盘重新读取预览（外部改过文件后点这里）")
            btn_refresh.clicked.connect(
                lambda _=False, r=ref: self._refresh_data_table_preview(r)
            )
            bar.addWidget(btn_refresh)
            btn_delete = QPushButton("删除")
            btn_delete.setToolTip("从列表移除并删除本地附件文件")
            btn_delete.clicked.connect(
                lambda _=False, r=ref: self._delete_data_table(r)
            )
            bar.addWidget(btn_delete)
            drawer.body_layout.addLayout(bar)

            preview = QTableWidget(0, 0)
            preview.setObjectName("dataTablePreview")
            preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
            preview.setSelectionMode(QAbstractItemView.NoSelection)
            preview.setFocusPolicy(Qt.NoFocus)
            preview.setMinimumHeight(120)
            preview.setMaximumHeight(220)
            preview.horizontalHeader().setStretchLastSection(False)
            snap = self._load_preview_for_ref(ref, force=False)
            self._fill_preview_table(preview, snap)
            if snap.merges:
                merge_lbl = QLabel("合并：" + "、".join(snap.merges))
                merge_lbl.setObjectName("dimLabel")
                merge_lbl.setWordWrap(True)
                drawer.body_layout.addWidget(merge_lbl)
            drawer.body_layout.addWidget(preview)
            drawer.header.clicked.connect(
                lambda _=False, d=drawer, bank=self._data_table_drawers: self._accordion(d, bank)
            )
            self.data_table_layout.addWidget(drawer)
            self._data_table_drawers.append(drawer)
            self._data_table_preview_tables[ref.relative_path] = preview
        if len(self._data_table_drawers) == 1:
            self._data_table_drawers[0].set_expanded(True)

    def _refresh_data_table_preview(self, ref: DataTableRef):
        self._load_preview_for_ref(ref, force=True)
        expanded_paths = {
            getattr(d, "_data_table_rel", ""): d._expanded for d in self._data_table_drawers
        }
        self._refresh_data_table_list()
        for d in self._data_table_drawers:
            rel = getattr(d, "_data_table_rel", "")
            if expanded_paths.get(rel) or rel == ref.relative_path:
                d.set_expanded(True)

    def _on_add_data_table(self):
        if not is_usable_test_name(self.node_data.test_name):
            QMessageBox.warning(self, "提示", "请先选择试验名称")
            return
        if self._project_root() is None:
            QMessageBox.warning(self, "提示", "请先加载项目以确定本地镜像路径")
            return

        chooser = QDialog(self)
        chooser.setWindowTitle("添加数据表")
        layout = QVBoxLayout(chooser)
        layout.addWidget(QLabel("请选择添加方式："))
        btn_upload = QPushButton("1 · 上传现有 Excel")
        btn_free = QPushButton("2 · 自由编辑")
        btn_template = QPushButton("3 · 模版")
        btn_template.setToolTip("从 templates/data_tables/ 复制一份")
        layout.addWidget(btn_upload)
        layout.addWidget(btn_free)
        layout.addWidget(btn_template)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(chooser.reject)
        layout.addWidget(buttons)

        chosen = {"mode": None}

        def pick(mode):
            chosen["mode"] = mode
            chooser.accept()

        btn_upload.clicked.connect(lambda: pick("upload"))
        btn_free.clicked.connect(lambda: pick("free"))
        btn_template.clicked.connect(lambda: pick("template"))
        if chooser.exec() != QDialog.Accepted or not chosen["mode"]:
            return
        if chosen["mode"] == "upload":
            self._add_upload_data_table()
        elif chosen["mode"] == "template":
            self._add_template_data_table()
        else:
            self._add_free_edit_data_table()

    def _add_upload_data_table(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Excel 数据表",
            "",
            "Excel 文件 (*.xlsx)",
        )
        if not path:
            return
        root = self._project_root()
        try:
            ref = upload_existing_xlsx(root, self.node_data.test_name, Path(path))
        except DataTableError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self._data_tables.append(ref)
        self._load_preview_for_ref(ref, force=True)
        self._refresh_data_table_list()
        if self._data_table_drawers:
            self._data_table_drawers[-1].set_expanded(True)

    def _add_free_edit_data_table(self):
        title, ok = QInputDialog.getText(self, "自由编辑", "数据表标题：")
        if not ok:
            return
        title = (title or "").strip()
        if not title:
            QMessageBox.warning(self, "提示", "请输入数据表标题")
            return
        root = self._project_root()
        try:
            ref = create_blank_workbook(root, self.node_data.test_name, title)
        except DataTableError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self._data_tables.append(ref)
        self._load_preview_for_ref(ref, force=True)
        self._refresh_data_table_list()
        if self._data_table_drawers:
            self._data_table_drawers[-1].set_expanded(True)

    def _add_template_data_table(self):
        templates = list_data_table_templates()
        if not templates:
            QMessageBox.information(
                self,
                "模版",
                "templates/data_tables/ 中暂无可用的 .xlsx 模版。",
            )
            return
        labels = [p.name for p in templates]
        choice, ok = QInputDialog.getItem(
            self, "选择模版", "模版文件：", labels, 0, False
        )
        if not ok or not choice:
            return
        src = next((p for p in templates if p.name == choice), None)
        if src is None:
            return
        root = self._project_root()
        try:
            ref = copy_from_template(root, self.node_data.test_name, src)
        except DataTableError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self._data_tables.append(ref)
        self._load_preview_for_ref(ref, force=True)
        self._refresh_data_table_list()
        if self._data_table_drawers:
            self._data_table_drawers[-1].set_expanded(True)

    def _open_data_table(self, ref: DataTableRef):
        root = self._project_root()
        if root is None:
            QMessageBox.warning(self, "提示", "请先加载项目以确定本地镜像路径")
            return
        path = resolve_attachment_path(root, ref)
        try:
            open_attachment(path)
        except DataTableError as exc:
            QMessageBox.warning(self, "无法打开", str(exc))

    def _delete_data_table(self, ref: DataTableRef):
        answer = QMessageBox.question(
            self,
            "删除数据表",
            f"是否删除「{ref.title}」？\n本地附件文件将一并删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        root = self._project_root()
        if root is not None:
            delete_attachment(resolve_attachment_path(root, ref))
        self._data_tables = [
            r for r in self._data_tables if r.relative_path != ref.relative_path
        ]
        self._data_table_preview_cache.pop(ref.relative_path, None)
        self._refresh_data_table_list()

    def _import_sample_ids_to_data_table(self, ref: DataTableRef):
        root = self._project_root()
        if root is None:
            QMessageBox.warning(self, "提示", "请先加载项目以确定本地镜像路径")
            return
        ids = self._existing_sample_ids()
        if not ids:
            QMessageBox.warning(self, "提示", "当前样品表没有可用的样品编号")
            return
        path = resolve_attachment_path(root, ref)
        try:
            import_sample_ids(path, ids)
        except DataTableError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        QMessageBox.information(
            self,
            "导入完成",
            f"已写入 {len(ids)} 个样品编号。点「刷新」可更新预览。",
        )

    def _find_std_row(self, want: TestStandard, used):
        want_key = want.ref_key()
        fallback = None
        for row in range(self.std_table.rowCount()):
            if row in used:
                continue
            chk = self.std_table.item(row, 0)
            data = (chk.data(Qt.UserRole) if chk else None) or {}
            key = self._std_ref_key(data)
            if key == want_key:
                return row
            std_no, chapter = key
            if want.chapter:
                continue
            if std_no == (want.standard_id or "") and fallback is None:
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
                order.append(self._std_ref_key(chk.data(Qt.UserRole) or {}))
                if len(order) == 1:
                    self.std_table.scrollToItem(chk)
            self._std_pick_order = order
        finally:
            self.std_table.blockSignals(False)
            self._std_updating = False
        for want in wanted:
            key = want.ref_key()
            if want.standard_desc:
                self._cond_edits[key] = want.standard_desc
            if want.standard_desc_en:
                self._cond_edits_en[key] = want.standard_desc_en
            if want.evaluation_req:
                self._eval_edits[key] = want.evaluation_req
            if want.evaluation_req_en:
                self._eval_edits_en[key] = want.evaluation_req_en
            if want.result_desc:
                self._result_edits[key] = want.result_desc
            if want.result_desc_en:
                self._result_edits_en[key] = want.result_desc_en
            if want.images:
                self._std_images[key] = list(want.images)
            defaults = list(want.key_params_defaults or want.key_params or [])
            if defaults:
                self._key_param_defaults[key] = defaults
                self._key_param_edits[key] = list(want.key_params or defaults)
                self._key_param_confirmed[key] = bool(want.key_params_confirmed)
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
            checked = equipment_should_restore(
                code,
                name,
                saved,
                legacy,
                match_codes=equipment_match_codes(data),
            )
            if chk is not None:
                chk.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.eq_table.blockSignals(False)
        self._refresh_eq_summary()

    @staticmethod
    def _compute_prev_end(state, node_data):
        """Return the end date of the node that precedes node_data in its Leg, or None."""
        from src.ui.gantt_utils import parse_date as _parse_date
        for leg in (state.legs or []):
            nodes = leg.nodes or []
            for idx, item in enumerate(nodes):
                if item is node_data and idx > 0:
                    prev = nodes[idx - 1]
                    d = _parse_date(prev.end_date)
                    return d if d.isValid() else None
        return None

    def _project_date_bounds(self):
        lo = QDate(1990, 1, 1)
        hi = QDate(9999, 12, 31)
        if self.proj_start_date and self.proj_start_date.isValid() and self.proj_start_date.year() >= 1990:
            lo = self.proj_start_date
        if self.proj_end_date and self.proj_end_date.isValid() and self.proj_end_date.year() >= 1990:
            hi = self.proj_end_date
        if hi < lo:
            hi = QDate(9999, 12, 31)
        return lo, hi

    def _apply_node_date_limits(self, start_lo, end_lo, hi):
        if hi < start_lo:
            hi = QDate(9999, 12, 31)
        if hi < end_lo:
            hi = QDate(9999, 12, 31)
        self.date_start.setMinimumDate(start_lo)
        self.date_start.setMaximumDate(hi)
        self.date_end.setMinimumDate(end_lo)
        self.date_end.setMaximumDate(hi)

    def _start_lower_bound(self) -> QDate:
        """Earliest allowed start date: max(project start, prev node end)."""
        lo, _ = self._project_date_bounds()
        if self._prev_node_end and self._prev_node_end.isValid() and self._prev_node_end.year() >= 1990:
            return self._prev_node_end if self._prev_node_end > lo else lo
        return lo

    def _on_node_dates_changed(self, *_args):
        """Node start date must be on or before end date, and not before the preceding node's end."""
        if getattr(self, "_updating_dates", False):
            return
        self._updating_dates = True
        try:
            lo = self._start_lower_bound()
            _, hi = self._project_date_bounds()
            self._apply_node_date_limits(lo, lo, hi)

            start = self.date_start.date()
            end = self.date_end.date()
            source = self.sender()

            if start < lo:
                start = lo
                self.date_start.setDate(start)

            if source is self.date_start:
                if start > end:
                    end = start
                    self.date_end.setDate(end)
            elif source is self.date_end:
                if end < start:
                    start = end
                    if start < lo:
                        start = lo
                    self.date_start.setDate(start)
            elif start > end:
                end = start
                self.date_end.setDate(end)

            self._apply_node_date_limits(lo, start, hi)
        finally:
            self._updating_dates = False
        self._refresh_eq_expiry()

    def _apply_schedule_dates(self) -> bool:
        start = self.date_start.date()
        end = self.date_end.date()
        if start > end:
            QMessageBox.warning(self, "错误", "开始日期不能晚于结束日期！")
            return False
        self.node_data.start_date = start.toString("yyyy-MM-dd")
        self.node_data.end_date = end.toString("yyyy-MM-dd")
        return True

    def save_and_close(self):
        if not self._apply_schedule_dates():
            return

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
            id_widget = self.table.cellWidget(row, 1)
            if id_widget is None:
                continue
            txt_id = id_widget.text().strip()
            if txt_id:
                desc_w = self.table.cellWidget(row, 2)
                combo_res = self.table.cellWidget(row, 3)
                res = combo_res.currentData()
                desc = desc_w.text().strip() if desc_w else ""
                samples.append(TestSample(
                    sample_id=txt_id,
                    result=res,
                    result_desc=desc or None,
                ))
        self.node_data.samples = samples
        self.node_data.data_tables = list(self._data_tables)
        self.accept()
