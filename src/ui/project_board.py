"""Hidden personal project board: projects fold open to their tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIntValidator, QPalette, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.io.project_board import (
    BOARD_COLUMNS,
    BoardGroup,
    BoardRow,
    filter_board_rows,
    format_iso_date,
    group_board_rows,
    highlight_html,
    highlight_spans,
    list_board_rows,
    locate_project_intranet_folder,
    open_folder_in_file_manager,
    request_intranet_share_mount,
    update_board_sample_qty,
    update_board_test_sample_qty,
)
from src.io.user_prefs import (
    board_intranet_year,
    parse_intranet_year,
    save_board_intranet_year,
)
from src.ui.theme import BG_INPUT, CYAN, OVERDUE, TEXT


COL_INDEX = 0
COL_PROJECT = 1
COL_SAMPLE = 2
COL_TO = 3
COL_TESTS = 4
COL_STANDARDS = 5
COL_STATUS = 6
COL_START = 7
COL_END = 8
COL_QTY = 9
COL_NOTES = 10

# JSON path for qty persistence — not Qt.UserRole, so autosize won't treat the
# path as display text when the cell is empty.
_QTY_PATH_ROLE = Qt.UserRole + 1
_QTY_LEG_ROLE = Qt.UserRole + 2
_QTY_NODE_ROLE = Qt.UserRole + 3

_PROGRESS_ON_CYAN = "#0A0E14"
_COL_PAD = 28
INTRANET_LOOKUP_TIMEOUT_MS = 20_000
_MIN_COL_WIDTHS = {
    COL_INDEX: 48,
    COL_STATUS: 110,
    COL_START: 100,
    COL_END: 100,
    COL_QTY: 72,
}
_MAX_COL_WIDTHS = {
    COL_QTY: 110,
}


class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ProjectIdLink(QLabel):
    def __init__(self, project_id: str, on_open=None, parent=None):
        super().__init__(parent)
        self._project_id = project_id
        self._on_open = on_open
        self.setObjectName("projectIdLink")
        self.setTextFormat(Qt.RichText)
        self.setCursor(Qt.PointingHandCursor)
        self.set_highlight("")

    def set_highlight(self, query: str) -> None:
        inner = highlight_html(self._project_id, query)
        self.setText(
            f'<span style="color:#00FFFF;text-decoration:underline">{inner}</span>'
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._on_open is not None:
                self._on_open(self._project_id)
            event.accept()
            return
        super().mousePressEvent(event)


class IntranetLookupWorker(QThread):
    done = Signal(int, str, object)

    def __init__(self, generation: int, project_id: str, year: int, parent=None):
        super().__init__(parent)
        self._generation = generation
        self._project_id = project_id
        self._year = year

    def run(self):
        try:
            result = locate_project_intranet_folder(self._project_id, self._year)
            path = str(result.path) if result.path else ""
            self.done.emit(self._generation, result.status, path)
        except Exception:
            self.done.emit(self._generation, "not_ready", "")


class SearchHighlightDelegate(QStyledItemDelegate):
    def __init__(self, query_fn, parent=None):
        super().__init__(parent)
        self._query_fn = query_fn

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setObjectName("boardQtyEdit")
        editor.setFrame(False)
        return editor

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect.adjusted(1, 1, -1, -1))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        query = (self._query_fn() or "").strip()
        text = str(index.data(Qt.DisplayRole) or "")
        if not query or not text or not highlight_spans(text, query):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = option.widget
        style = widget.style() if widget is not None else None
        if style is None:
            super().paint(painter, option, index)
            return
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget)
        if not rect.isValid():
            rect = option.rect
        painter.save()
        painter.setClipRect(rect)
        fm = option.fontMetrics
        x = rect.x()
        highlight_bg = QColor(0, 255, 255, 140)
        highlight_fg = QColor(_PROGRESS_ON_CYAN)
        fg = opt.palette.color(QPalette.ColorRole.Text)
        cursor = 0
        for start, end in highlight_spans(text, query):
            if start > cursor:
                x = _draw_chunk(painter, fm, rect, x, text[cursor:start], fg, None)
            x = _draw_chunk(
                painter, fm, rect, x, text[start:end], highlight_fg, highlight_bg
            )
            cursor = end
        if cursor < len(text):
            _draw_chunk(painter, fm, rect, x, text[cursor:], fg, None)
        painter.restore()


def _draw_chunk(painter, fm, rect: QRect, x: int, chunk: str, fg: QColor, bg):
    if not chunk:
        return x
    width = fm.horizontalAdvance(chunk)
    if bg is not None:
        painter.fillRect(x, rect.y() + 1, width, max(rect.height() - 2, 1), bg)
    painter.setPen(fg)
    painter.drawText(QRect(x, rect.y(), width, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, chunk)
    return x + width


class ProjectBoardPage(QWidget):
    leave_requested = Signal()

    def __init__(self, data_root: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._data_root = data_root
        self._today: date = date.today()
        self._rows: List[BoardRow] = []
        self._lookup_gen = 0
        self._lookup_busy = False
        self._lookup_project_id = ""
        self._lookup_workers: List[IntranetLookupWorker] = []
        self._lookup_timer = QTimer(self)
        self._lookup_timer.setSingleShot(True)
        self._lookup_timer.timeout.connect(self._on_intranet_lookup_timeout)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        panel = QGroupBox("项目看板")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 16, 10, 10)
        panel_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("搜索"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("项目号 / 样品 / 试验 / 标准 / TO号")
        self.txt_search.setMinimumWidth(180)
        self.txt_search.setMaximumWidth(320)
        self.txt_search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.txt_search)
        self.txt_year = QLineEdit()
        self.txt_year.setObjectName("boardYear")
        self.txt_year.setMaxLength(4)
        self.txt_year.setFixedWidth(72)
        self.txt_year.setAlignment(Qt.AlignCenter)
        self.txt_year.setValidator(QIntValidator(2000, 2099, self.txt_year))
        self.txt_year.setToolTip("公盘目录年份（车载电子/{年}年）")
        self.txt_year.setText(str(board_intranet_year(self._data_root)))
        self.txt_year.editingFinished.connect(self._persist_year)
        toolbar.addWidget(self.txt_year)
        toolbar.addStretch(1)
        self.btn_back = QPushButton("返回当前项目")
        self.btn_back.setObjectName("poolToggle")
        self.btn_back.clicked.connect(self.leave_requested.emit)
        toolbar.addWidget(self.btn_back)
        panel_layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setObjectName("projectBoardTable")
        self.tree.setColumnCount(len(BOARD_COLUMNS))
        self.tree.setHeaderLabels(list(BOARD_COLUMNS))
        # Qty edits start only via editItem; other columns stay non-editable.
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setWordWrap(False)
        self.tree.setTextElideMode(Qt.ElideNone)
        self.tree.setRootIsDecorated(False)
        self.tree.setAnimated(True)
        self.tree.setItemsExpandable(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setIndentation(12)
        self.tree.setUniformRowHeights(False)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tree.setItemDelegate(SearchHighlightDelegate(self._search_query, self.tree))
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemExpanded.connect(self._sync_group_arrow)
        self.tree.itemCollapsed.connect(self._sync_group_arrow)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        panel_layout.addWidget(self.tree, stretch=1)

        self.lbl_count = QLabel("0 个项目")
        self.lbl_count.setObjectName("dimLabel")
        panel_layout.addWidget(self.lbl_count)

        layout.addWidget(panel)

    def _search_query(self) -> str:
        return self.txt_search.text()

    def _year_value(self) -> int:
        parsed = parse_intranet_year(self.txt_year.text())
        if parsed is not None:
            return parsed
        year = board_intranet_year(self._data_root)
        self.txt_year.setText(str(year))
        return year

    def _persist_year(self) -> None:
        year = self._year_value()
        self.txt_year.setText(str(year))
        save_board_intranet_year(year, self._data_root)

    def _open_project_folder(self, project_id: str) -> None:
        if self._lookup_busy:
            return
        year = self._year_value()
        save_board_intranet_year(year, self._data_root)
        self._lookup_workers = [w for w in self._lookup_workers if w.isRunning()]
        self._lookup_gen += 1
        gen = self._lookup_gen
        self._lookup_busy = True
        self._lookup_project_id = project_id
        try:
            self.setCursor(Qt.WaitCursor)
        except RuntimeError:
            pass
        worker = IntranetLookupWorker(gen, project_id, year, parent=self)
        worker.done.connect(self._on_intranet_lookup_done)
        self._lookup_workers.append(worker)
        worker.start()
        self._lookup_timer.start(INTRANET_LOOKUP_TIMEOUT_MS)

    def _finish_intranet_lookup(self, generation: int) -> bool:
        if generation != self._lookup_gen or not self._lookup_busy:
            return False
        self._lookup_busy = False
        self._lookup_timer.stop()
        try:
            self.unsetCursor()
        except RuntimeError:
            pass
        return True

    def _on_intranet_lookup_timeout(self) -> None:
        if not self._finish_intranet_lookup(self._lookup_gen):
            return
        year = self._year_value()
        QMessageBox.information(
            self,
            "未找到公盘目录",
            f"查找 {year}年 公盘目录超时。请确认公盘已连接后再试。",
        )

    def _on_intranet_lookup_done(self, generation: int, status: str, path) -> None:
        if not self._finish_intranet_lookup(generation):
            return
        year = self._year_value()
        if status == "found" and path:
            open_folder_in_file_manager(path)
            return
        if status == "not_ready":
            request_intranet_share_mount()
            QMessageBox.information(
                self,
                "未找到公盘目录",
                f"无法访问 {year}年 公盘目录。请确认公盘已连接后再试。",
            )
            return
        QMessageBox.information(
            self,
            "未找到公盘目录",
            f"在 {year}年 下未找到项目 {self._lookup_project_id} 对应的公盘目录。",
        )

    def reload(self, *, today: Optional[date] = None) -> None:
        self._today = today or date.today()
        self._rows = list_board_rows(self._data_root, today=self._today)
        self._apply_filter()

    def visible_rows(self) -> List[BoardRow]:
        return filter_board_rows(self._rows, self.txt_search.text())

    def visible_groups(self) -> List[BoardGroup]:
        return group_board_rows(self.visible_rows(), today=self._today)

    def _apply_filter(self) -> None:
        query = (self.txt_search.text() or "").strip()
        groups = self.visible_groups()
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            for index, group in enumerate(groups):
                parent = self._make_group_item(index, group)
                self.tree.addTopLevelItem(parent)
                self._set_project_link(parent, group.project_id, query)
                for test in group.tests:
                    child = self._make_test_item(test)
                    parent.addChild(child)
                    self._set_progress(child, test.progress, test.overdue)
                parent.setExpanded(bool(query))
                self._sync_group_arrow(parent)
                self._set_progress(parent, group.progress, group.overdue)
        finally:
            self.tree.blockSignals(False)
        self._autosize_columns()
        test_count = sum(len(group.tests) for group in groups)
        self.lbl_count.setText(f"{len(groups)} 个项目 · {test_count} 个试验")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column == COL_QTY:
            if item.flags() & Qt.ItemIsEditable:
                self.tree.editItem(item, COL_QTY)
            return
        if column == COL_PROJECT:
            return
        if item.parent() is None and item.childCount():
            item.setExpanded(not item.isExpanded())

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != COL_QTY:
            return
        raw = item.data(COL_QTY, _QTY_PATH_ROLE)
        if not raw:
            return
        path = Path(str(raw))
        qty = (item.text(COL_QTY) or "").strip()
        if item.text(COL_QTY) != qty:
            self.tree.blockSignals(True)
            try:
                item.setText(COL_QTY, qty)
            finally:
                self.tree.blockSignals(False)

        parent = item.parent()
        if parent is None:
            if not update_board_sample_qty(path, qty):
                return
            self._rows = [
                row if row.json_path != path else replace(row, project_sample_qty=qty)
                for row in self._rows
            ]
            return

        leg_raw = item.data(COL_QTY, _QTY_LEG_ROLE)
        node_raw = item.data(COL_QTY, _QTY_NODE_ROLE)
        if leg_raw is None or node_raw is None:
            return
        leg_index = int(leg_raw)
        node_index = int(node_raw)
        if not update_board_test_sample_qty(path, leg_index, node_index, qty):
            return
        self._rows = [
            row
            if not (
                row.json_path == path
                and row.leg_index == leg_index
                and row.node_index == node_index
            )
            else replace(row, sample_qty=qty)
            for row in self._rows
        ]

    def _sync_group_arrow(self, item: QTreeWidgetItem) -> None:
        if item.parent() is not None:
            return
        n = item.data(COL_INDEX, Qt.UserRole)
        if n is None:
            return
        arrow = "▼" if item.isExpanded() else "▶"
        item.setText(COL_INDEX, f"{arrow} {n}")

    def _make_group_item(self, index: int, group: BoardGroup) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            [
                f"▶ {index + 1}",
                "",
                group.sample_name,
                "",
                f"{len(group.tests)} 项",
                "",
                "",
                format_iso_date(group.start),
                format_iso_date(group.end),
                group.sample_qty,
                group.notes,
            ]
        )
        item.setData(COL_INDEX, Qt.UserRole, index + 1)
        item.setData(COL_PROJECT, Qt.UserRole, group.project_id)
        item.setData(COL_QTY, _QTY_PATH_ROLE, str(group.json_path))
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        item.setForeground(COL_INDEX, QBrush(QColor("#00FFFF")))
        return item

    def _make_test_item(self, row: BoardRow) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            [
                "·",
                "",
                "",
                row.to_number,
                row.test_name,
                row.standards_text,
                "",
                format_iso_date(row.start),
                format_iso_date(row.end),
                row.sample_qty,
                row.notes,
            ]
        )
        item.setData(COL_QTY, _QTY_PATH_ROLE, str(row.json_path))
        if row.leg_index is not None and row.node_index is not None:
            item.setData(COL_QTY, _QTY_LEG_ROLE, row.leg_index)
            item.setData(COL_QTY, _QTY_NODE_ROLE, row.node_index)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
        item.setForeground(COL_INDEX, QBrush(QColor("#8B949E")))
        return item

    def _set_project_link(self, item: QTreeWidgetItem, project_id: str, query: str) -> None:
        link = ProjectIdLink(project_id, self._open_project_folder)
        link.set_highlight(query)
        self.tree.setItemWidget(item, COL_PROJECT, link)

    def _set_progress(
        self,
        item: QTreeWidgetItem,
        progress: Optional[float],
        overdue: bool,
    ) -> None:
        item.setText(COL_STATUS, "")
        if progress is None:
            return
        pct = int(round(progress * 100))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(pct)
        bar.setFormat(f"{pct}%")
        bar.setTextVisible(True)
        bar.setFixedHeight(18)
        bar.setMinimumWidth(110)
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        _paint_progress_bar(bar, overdue)
        self.tree.setItemWidget(item, COL_STATUS, bar)

    def _autosize_columns(self) -> None:
        fm = self.tree.fontMetrics()
        header_fm = self.tree.header().fontMetrics()
        for col in range(self.tree.columnCount()):
            width = header_fm.horizontalAdvance(BOARD_COLUMNS[col]) + _COL_PAD
            for i in range(self.tree.topLevelItemCount()):
                width = max(width, self._item_col_width(self.tree.topLevelItem(i), col, 0, fm))
            width = max(width, _MIN_COL_WIDTHS.get(col, 40))
            if col in _MAX_COL_WIDTHS:
                width = min(width, _MAX_COL_WIDTHS[col])
            self.tree.setColumnWidth(col, width)

    def _item_col_width(self, item: QTreeWidgetItem, col: int, depth: int, fm) -> int:
        extra = self.tree.indentation() * depth if col == COL_INDEX else 0
        width = 0
        text = item.text(col)
        # Project column text lives in a widget; fall back to UserRole id for width.
        if not text and col == COL_PROJECT:
            data = item.data(col, Qt.UserRole)
            if isinstance(data, str) and data:
                text = data
        if text:
            width = fm.horizontalAdvance(text) + _COL_PAD + extra
        widget = self.tree.itemWidget(item, col)
        if widget is not None:
            hint = widget.sizeHint().width()
            if hint > 0:
                width = max(width, hint + 12)
        for i in range(item.childCount()):
            width = max(width, self._item_col_width(item.child(i), col, depth + 1, fm))
        return width


def _paint_progress_bar(bar: QProgressBar, overdue: bool) -> None:
    if overdue:
        bar.setObjectName("overdueProgress")
        fg = TEXT
        chunk = OVERDUE
    else:
        fg = _PROGRESS_ON_CYAN
        chunk = CYAN
    bar.setStyleSheet(
        f"QProgressBar {{ color: {fg}; background-color: {BG_INPUT}; "
        f"border: 1px solid #1F2A37; border-radius: 6px; text-align: center; }}"
        f"QProgressBar::chunk {{ background-color: {chunk}; border-radius: 5px; }}"
    )
    palette = bar.palette()
    color = QColor(fg)
    palette.setColor(QPalette.ColorRole.Text, color)
    palette.setColor(QPalette.ColorRole.WindowText, color)
    palette.setColor(QPalette.ColorRole.HighlightedText, color)
    bar.setPalette(palette)
