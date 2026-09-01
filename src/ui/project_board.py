"""Hidden personal project board: projects fold open to their tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QRect, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPalette, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
    project_intranet_url,
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

_PROGRESS_ON_CYAN = "#0A0E14"
_COL_PAD = 28
_MIN_COL_WIDTHS = {
    COL_INDEX: 48,
    COL_STATUS: 110,
    COL_START: 100,
    COL_END: 100,
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
    def __init__(self, project_id: str, url: str = "", parent=None):
        super().__init__(parent)
        self._project_id = project_id
        self._url = (url or "").strip()
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
        if event.button() == Qt.LeftButton and self._url:
            QDesktopServices.openUrl(QUrl(self._url))
            event.accept()
            return
        super().mousePressEvent(event)


class SearchHighlightDelegate(QStyledItemDelegate):
    def __init__(self, query_fn, parent=None):
        super().__init__(parent)
        self._query_fn = query_fn

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
        self.txt_search.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.txt_search, stretch=1)
        self.btn_back = QPushButton("返回报告")
        self.btn_back.setObjectName("poolToggle")
        self.btn_back.clicked.connect(self.leave_requested.emit)
        toolbar.addWidget(self.btn_back)
        panel_layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setObjectName("projectBoardTable")
        self.tree.setColumnCount(len(BOARD_COLUMNS))
        self.tree.setHeaderLabels(list(BOARD_COLUMNS))
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
        self._autosize_columns()
        test_count = sum(len(group.tests) for group in groups)
        self.lbl_count.setText(f"{len(groups)} 个项目 · {test_count} 个试验")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column == COL_PROJECT:
            return
        if item.parent() is None and item.childCount():
            item.setExpanded(not item.isExpanded())

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
                "",
                row.notes,
            ]
        )
        item.setForeground(COL_INDEX, QBrush(QColor("#8B949E")))
        return item

    def _set_project_link(self, item: QTreeWidgetItem, project_id: str, query: str) -> None:
        link = ProjectIdLink(project_id, project_intranet_url(project_id))
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
            self.tree.setColumnWidth(col, width)

    def _item_col_width(self, item: QTreeWidgetItem, col: int, depth: int, fm) -> int:
        extra = self.tree.indentation() * depth if col == COL_INDEX else 0
        width = 0
        text = item.text(col)
        if not text:
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
