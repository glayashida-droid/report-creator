"""Variable-width wrapping chips for the left-panel candidate pool."""

from typing import Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QMimeData, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QLabel, QLayout, QScrollArea, QSizePolicy, QWidget

CHIP_H = 26
CHIP_PAD = 20
CANDIDATE_TEST_MIME = "application/x-reach-candidate-test"

_pool_drag_depth = 0


def begin_pool_drag() -> None:
    global _pool_drag_depth
    _pool_drag_depth += 1


def end_pool_drag() -> None:
    global _pool_drag_depth
    _pool_drag_depth = max(0, _pool_drag_depth - 1)


def pool_drag_active() -> bool:
    return _pool_drag_depth > 0


def candidate_test_from_mime(mime: QMimeData) -> str:
    raw = mime.data(CANDIDATE_TEST_MIME)
    if raw:
        return bytes(raw).decode("utf-8").strip()
    return (mime.text() or "").strip()


class PoolChip(QLabel):
    """Draggable chip; full name is kept in toolTip even when elided."""

    def __init__(self, full_name: str, parent=None):
        super().__init__(full_name, parent)
        self.setObjectName("poolChip")
        self.setToolTip(full_name)
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFixedHeight(CHIP_H)
        self.setCursor(Qt.OpenHandCursor)
        self._drag_start: Optional[QPoint] = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self._drag_start is None:
            super().mouseMoveEvent(event)
            return
        if (
            event.position().toPoint() - self._drag_start
        ).manhattanLength() < QApplication.startDragDistance():
            return
        name = (self.toolTip() or self.text() or "").strip()
        if not name:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(CANDIDATE_TEST_MIME, name.encode("utf-8"))
        mime.setText(name)
        drag.setMimeData(mime)
        begin_pool_drag()
        try:
            drag.exec(Qt.CopyAction)
        finally:
            # Defer until after any dropEvent singleShot handlers so inserts stay guarded.
            QTimer.singleShot(0, end_pool_drag)
        self._drag_start = None


def chip_display_width(text, font_metrics, viewport_width, padding=CHIP_PAD):
    """Pixel width for one chip: text size, capped to the pool viewport."""
    need = font_metrics.horizontalAdvance(text or "") + padding
    view = max(int(viewport_width or 0), padding + 8)
    return max(padding + 8, min(need, view))


class FlowLayout(QLayout):
    """Left-to-right wrap. Each item keeps its own size hint."""

    def __init__(self, parent=None, margin=4, hspacing=4, vspacing=4):
        super().__init__(parent)
        self._items = []
        self._hspacing = hspacing
        self._vspacing = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        m = self.contentsMargins()
        return QSize(40 + m.left() + m.right(), CHIP_H + m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        space_x = self._hspacing
        space_y = self._vspacing
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + space_x
            if next_x - space_x > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + hint.width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


class CandidatePoolList(QScrollArea):
    """Wrapping chips sized to each name. Elides only when a name exceeds the panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("candidatePoolList")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        self._host = QWidget()
        self._host.setObjectName("candidatePoolHost")
        self._flow = FlowLayout(self._host)
        self.setWidget(self._host)
        self._chips = []

    def sizeHint(self):
        return QSize(120, 80)

    def minimumSizeHint(self):
        return QSize(60, 40)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_grid()

    def clear(self):
        while self._flow.count():
            item = self._flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._chips = []

    def set_items(self, items):
        self.clear()
        for text in items or []:
            chip = PoolChip(text)
            self._flow.addWidget(chip)
            self._chips.append(chip)
        self.fit_grid()

    def fit_grid(self):
        viewport_w = self.viewport().width()
        if viewport_w <= 1:
            viewport_w = 10**6
        else:
            viewport_w = max(viewport_w - 8, CHIP_PAD + 8)
        fm = self.fontMetrics()
        for chip in self._chips:
            full = chip.toolTip() or ""
            fm = chip.fontMetrics()
            width = chip_display_width(full, fm, viewport_w)
            inner = max(width - CHIP_PAD, 8)
            if fm.horizontalAdvance(full) > inner:
                chip.setText(fm.elidedText(full, Qt.ElideRight, inner))
            else:
                chip.setText(full)
            chip.setFixedWidth(width)
        self._host.updateGeometry()
