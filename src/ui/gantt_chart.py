"""Interactive Gantt chart for Leg test schedules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional, Tuple

from PySide6.QtCore import QDate, QPoint, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractSlider,
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QToolTip,
    QWidget,
)

from src.models.project_state import ProjectState, TestLeg, TestNode
from src.ui.gantt_utils import (
    DEFAULT_ZOOM_INDEX,
    ZOOM_LEVELS,
    DateRange,
    cascade_subsequent_nodes,
    clamp_range,
    clamp_resize_end,
    clamp_resize_start,
    compute_axis_range,
    day_offset,
    format_date,
    label_tooltip_if_elided,
    leg_has_overlap,
    leg_range,
    node_range,
    overlapped_node_ids_in_leg,
    parse_date,
    range_exceeds_project_bounds,
    restore_leg_dates,
    set_node_range,
    shift_scheduled_nodes,
    snapshot_leg_dates,
    test_label,
)

LEFT_COL_WIDTH = 132
ROW_HEIGHT = 36
LEG_HEADER_HEIGHT = 28
TIMELINE_HEADER_HEIGHT = 28
BAR_HEIGHT = 22
LEG_BAR_HEIGHT = 16
HANDLE_WIDTH = 8
MIN_BAR_DAYS = 1

_CYAN = QColor("#00FFFF")
_CYAN_TODAY = QColor(0, 255, 255, 32)
_MAGENTA = QColor("#FF00FF")
_MAGENTA_DIM = QColor(255, 0, 255, 90)
_MAGENTA_LEG = QColor(255, 0, 255, 40)
_MAGENTA_LEG_BORDER = QColor(255, 0, 255, 120)
_BG = QColor("#12181F")
_BG_LEFT = QColor("#0D1117")
_TEXT = QColor("#E6EDF3")
_TEXT_DIM = QColor("#8B949E")
_BORDER = QColor("#1F2A37")
_UNSCHEDULED = QColor("#8B949E")
_OVERLAP = QColor("#FF6B35")
_OVERLAP_DIM = QColor(255, 107, 53, 110)


class DragMode(Enum):
    NONE = auto()
    PAN = auto()
    MOVE = auto()
    MOVE_LEG = auto()
    RESIZE_START = auto()
    RESIZE_END = auto()
    CREATE = auto()


@dataclass
class GanttRow:
    kind: str  # leg_header | test
    leg: Optional[TestLeg]
    node: Optional[TestNode]
    label: str


class GanttViewState:
    """Shared layout data for the fixed label column and scrollable timeline."""

    def __init__(self, state: ProjectState):
        self.project_state = state
        self.rows: List[GanttRow] = []
        self.axis = DateRange(QDate.currentDate(), QDate.currentDate())
        self.zoom_index = DEFAULT_ZOOM_INDEX
        self.pixels_per_day = 24.0
        self.proj_start = QDate()
        self.proj_end = QDate()
        self.hover_row = -1
        self.overlap_node_ids: set[int] = set()
        self.extra_future_days = 0

    def visible_days(self) -> int:
        return ZOOM_LEVELS[self.zoom_index]

    def refresh(self) -> None:
        self.proj_start = parse_date(self.project_state.test_start_date)
        self.proj_end = parse_date(self.project_state.test_end_date)
        self.rows = self._build_rows()
        self.overlap_node_ids = set()
        for leg in self.project_state.legs or []:
            self.overlap_node_ids.update(overlapped_node_ids_in_leg(leg))
        self.axis = compute_axis_range(
            self.project_state.legs,
            self.proj_start,
            self.proj_end,
            QDate.currentDate(),
            self.visible_days(),
        )
        if self.extra_future_days > 0 and self.axis.is_valid():
            self.axis = DateRange(
                self.axis.start,
                self.axis.end.addDays(self.extra_future_days),
            )

    def extend_axis_end(self, days: int) -> bool:
        if days <= 0 or not self.axis.is_valid():
            return False
        self.extra_future_days += days
        self.axis = DateRange(self.axis.start, self.axis.end.addDays(days))
        return True

    def _build_rows(self) -> List[GanttRow]:
        rows: List[GanttRow] = []
        for leg in self.project_state.legs or []:
            rows.append(
                GanttRow(
                    kind="leg_header",
                    leg=leg,
                    node=None,
                    label=leg.leg_name or leg.leg_id,
                )
            )
            for node in leg.nodes or []:
                rows.append(
                    GanttRow(
                        kind="test",
                        leg=leg,
                        node=node,
                        label=test_label(node),
                    )
                )
        return rows

    def timeline_days(self) -> int:
        return max(self.axis.days(), 1)

    def content_height(self) -> int:
        total = TIMELINE_HEADER_HEIGHT
        for row in self.rows:
            total += LEG_HEADER_HEIGHT if row.kind == "leg_header" else ROW_HEIGHT
        return max(total + 8, 160)

    def timeline_content_width(self) -> int:
        return int(round(self.timeline_days() * self.pixels_per_day)) + 24

    def row_top(self, row_index: int) -> int:
        y = TIMELINE_HEADER_HEIGHT
        for i, row in enumerate(self.rows):
            if i == row_index:
                return y
            y += LEG_HEADER_HEIGHT if row.kind == "leg_header" else ROW_HEIGHT
        return y

    def row_height(self, row_index: int) -> int:
        if 0 <= row_index < len(self.rows):
            return LEG_HEADER_HEIGHT if self.rows[row_index].kind == "leg_header" else ROW_HEIGHT
        return ROW_HEIGHT

    def row_at(self, y: int) -> int:
        cursor = TIMELINE_HEADER_HEIGHT
        for i, row in enumerate(self.rows):
            h = LEG_HEADER_HEIGHT if row.kind == "leg_header" else ROW_HEIGHT
            if cursor <= y < cursor + h:
                return i
            cursor += h
        return -1

    def x_for_day(self, day: QDate) -> float:
        return day_offset(self.axis.start, day) * self.pixels_per_day

    def day_at_x(self, x: float) -> QDate:
        day_index = int(x / self.pixels_per_day)
        day_index = max(0, min(day_index, self.timeline_days() - 1))
        return self.axis.start.addDays(day_index)


class GanttLeftPanel(QWidget):
    """Fixed label column; stays visible while the timeline scrolls horizontally."""

    hover_changed = Signal(int)

    def __init__(self, view: GanttViewState, parent=None):
        super().__init__(parent)
        self._view = view
        self.setFixedWidth(LEFT_COL_WIDTH)
        self.setMouseTracking(True)

    def _label_font(self, row: GanttRow) -> QFont:
        font = self.font()
        font.setBold(row.kind == "leg_header")
        return font

    def _label_max_width(self) -> int:
        return max(self.width() - 20, 1)

    def _label_display(self, row: GanttRow) -> tuple[str, str]:
        full = (row.label or "").strip()
        if not full:
            return "", ""
        fm = QFontMetrics(self._label_font(row))
        elided = fm.elidedText(full, Qt.ElideRight, self._label_max_width())
        return elided, label_tooltip_if_elided(full, elided)

    def set_view(self, view: GanttViewState) -> None:
        self._view = view

    def sizeHint(self) -> QSize:
        return QSize(LEFT_COL_WIDTH, self._view.content_height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def refresh_geometry(self) -> None:
        h = self._view.content_height()
        self.setMinimumSize(LEFT_COL_WIDTH, h)
        self.resize(LEFT_COL_WIDTH, h)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), _BG_LEFT)
        painter.setPen(QPen(_BORDER, 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        painter.fillRect(0, 0, self.width(), TIMELINE_HEADER_HEIGHT, _BG_LEFT)
        painter.setPen(QPen(_BORDER, 1))
        painter.drawLine(0, TIMELINE_HEADER_HEIGHT, self.width(), TIMELINE_HEADER_HEIGHT)

        y = TIMELINE_HEADER_HEIGHT
        for i, row in enumerate(self._view.rows):
            h = LEG_HEADER_HEIGHT if row.kind == "leg_header" else ROW_HEIGHT
            painter.fillRect(0, y, self.width(), h, _BG_LEFT)
            painter.setPen(QPen(_BORDER, 1))
            painter.drawLine(0, y + h - 1, self.width(), y + h - 1)

            font = self._label_font(row)
            painter.setFont(font)
            if row.kind == "leg_header":
                painter.setPen(_CYAN)
            elif row.node is not None and id(row.node) in self._view.overlap_node_ids:
                painter.setPen(_OVERLAP)
            else:
                painter.setPen(_TEXT if i == self._view.hover_row else _TEXT_DIM)
            elided, _ = self._label_display(row)
            painter.drawText(8, y, self.width() - 12, h, Qt.AlignVCenter | Qt.AlignLeft, elided)
            y += h

    def mouseMoveEvent(self, event: QMouseEvent):
        row_index = self._view.row_at(event.position().toPoint().y())
        if row_index != self._view.hover_row:
            self._view.hover_row = row_index
            self.hover_changed.emit(row_index)
            self.update()
        if 0 <= row_index < len(self._view.rows):
            _, tip = self._label_display(self._view.rows[row_index])
            if tip:
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
            else:
                QToolTip.hideText()
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class GanttTimelinePanel(QWidget):
    schedule_changed = Signal()
    hover_changed = Signal(int)

    def __init__(self, view: GanttViewState, scroll_area: QScrollArea, parent=None):
        super().__init__(parent)
        self._view = view
        self._scroll_area = scroll_area

        self._drag_mode = DragMode.NONE
        self._pan_anchor = QPoint()
        self._pan_scroll = (0, 0)
        self._drag_leg: Optional[TestLeg] = None
        self._drag_node: Optional[TestNode] = None
        self._drag_snapshot: dict[int, Tuple[Optional[str], Optional[str]]] = {}
        self._orig_range: Optional[DateRange] = None
        self._orig_leg_range: Optional[DateRange] = None
        self._drag_start_offset = 0
        self._create_anchor_day: Optional[QDate] = None
        self._intended_range: Optional[DateRange] = None

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

    def set_view(self, view: GanttViewState) -> None:
        self._view = view

    def sizeHint(self) -> QSize:
        viewport_w = max(self._scroll_area.viewport().width(), 320)
        return QSize(max(self._view.timeline_content_width(), viewport_w), self._view.content_height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def rebuild_metrics(self, viewport_w: int) -> None:
        timeline_viewport = max(viewport_w, 120)
        self._view.pixels_per_day = timeline_viewport / float(self._view.visible_days())
        hint = self.sizeHint()
        self.setMinimumSize(hint)
        self.resize(hint)
        self.updateGeometry()
        self.update()

    def _bar_rect(
        self, row_index: int, rng: DateRange, bar_height: int = BAR_HEIGHT
    ) -> Tuple[float, float, float, float]:
        top = self._view.row_top(row_index)
        h = self._view.row_height(row_index)
        y = top + (h - bar_height) / 2.0
        x1 = self._view.x_for_day(rng.start)
        x2 = self._view.x_for_day(rng.end) + self._view.pixels_per_day
        return x1, y, max(x2 - x1, self._view.pixels_per_day), bar_height

    def _hit_test_bar(self, pos: QPoint) -> Tuple[int, DragMode]:
        row_index = self._view.row_at(pos.y())
        if row_index < 0:
            return -1, DragMode.NONE
        row = self._view.rows[row_index]
        if row.kind == "leg_header" and row.leg is not None:
            rng = leg_range(row.leg)
            if not rng:
                return row_index, DragMode.NONE
            x, y, w, h = self._bar_rect(row_index, rng, LEG_BAR_HEIGHT)
            if x <= pos.x() <= x + w and y <= pos.y() <= y + h:
                return row_index, DragMode.MOVE_LEG
            return row_index, DragMode.NONE
        if row.kind != "test" or row.node is None:
            return row_index, DragMode.NONE

        rng = node_range(row.node)
        if rng:
            x, y, w, h = self._bar_rect(row_index, rng)
            row_top = self._view.row_top(row_index)
            row_h = self._view.row_height(row_index)
            in_row = row_top <= pos.y() < row_top + row_h
            if not (in_row and x <= pos.x() <= x + w):
                return row_index, DragMode.NONE
            if pos.x() <= x + HANDLE_WIDTH:
                return row_index, DragMode.RESIZE_START
            if pos.x() >= x + w - HANDLE_WIDTH:
                return row_index, DragMode.RESIZE_END
            return row_index, DragMode.MOVE
        return row_index, DragMode.CREATE

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), _BG)

        self._paint_timeline_header(painter)
        y = TIMELINE_HEADER_HEIGHT
        for i, row in enumerate(self._view.rows):
            h = LEG_HEADER_HEIGHT if row.kind == "leg_header" else ROW_HEIGHT
            painter.fillRect(0, y, self.width(), h, _BG)
            painter.setPen(QPen(_BORDER, 1))
            painter.drawLine(0, y + h - 1, self.width(), y + h - 1)
            y += h

        self._paint_today_column(painter)
        self._paint_grid(painter)

        y = TIMELINE_HEADER_HEIGHT
        for i, row in enumerate(self._view.rows):
            h = LEG_HEADER_HEIGHT if row.kind == "leg_header" else ROW_HEIGHT
            if row.kind == "leg_header":
                self._paint_leg_bar(painter, row, i)
            elif row.kind == "test":
                self._paint_test_bar(painter, row, i, y, h)
            y += h

        if not self._view.rows:
            painter.setPen(_TEXT_DIM)
            painter.drawText(16, TIMELINE_HEADER_HEIGHT + 16, 320, 32, Qt.AlignVCenter | Qt.AlignLeft,
                           "当前没有试验，请先在 Leg 排布中添加。")

    def _paint_today_column(self, painter: QPainter):
        if not self._view.axis.is_valid() or self._view.pixels_per_day <= 0:
            return
        today = QDate.currentDate()
        if today < self._view.axis.start or today > self._view.axis.end:
            return
        x = int(self._view.x_for_day(today))
        w = max(int(round(self._view.pixels_per_day)), 1)
        painter.fillRect(x, 0, w, self.height(), _CYAN_TODAY)

    def _paint_grid(self, painter: QPainter):
        if not self._view.axis.is_valid() or self._view.pixels_per_day <= 0:
            return
        painter.setPen(QPen(_BORDER, 1))
        for i in range(self._view.timeline_days() + 1):
            x = int(self._view.x_for_day(self._view.axis.start.addDays(i)))
            painter.drawLine(x, TIMELINE_HEADER_HEIGHT, x, self.height())

    def _paint_timeline_header(self, painter: QPainter):
        painter.fillRect(0, 0, self.width(), TIMELINE_HEADER_HEIGHT, _BG)
        painter.setPen(QPen(_BORDER, 1))
        painter.drawLine(0, TIMELINE_HEADER_HEIGHT, self.width(), TIMELINE_HEADER_HEIGHT)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(_TEXT_DIM)
        if not self._view.axis.is_valid():
            return
        last_label_x = -999
        step = 1 if self._view.pixels_per_day >= 22 else 2 if self._view.pixels_per_day >= 12 else 7
        today = QDate.currentDate()
        for i in range(self._view.timeline_days()):
            day = self._view.axis.start.addDays(i)
            x = int(self._view.x_for_day(day))
            is_today = day == today
            if i % step != 0 and not is_today:
                continue
            if x - last_label_x < 28 and not is_today:
                continue
            font = painter.font()
            font.setBold(is_today)
            painter.setFont(font)
            painter.setPen(_CYAN if is_today else _TEXT_DIM)
            painter.drawText(x + 3, 4, 48, TIMELINE_HEADER_HEIGHT - 6, Qt.AlignVCenter | Qt.AlignLeft,
                             day.toString("MM-dd"))
            last_label_x = x

    def _paint_leg_bar(self, painter, row: GanttRow, row_index: int):
        if row.leg is None:
            return
        rng = leg_range(row.leg)
        if not rng:
            return
        x, by, bw, bh = self._bar_rect(row_index, rng, LEG_BAR_HEIGHT)
        painter.setBrush(_MAGENTA_LEG)
        painter.setPen(QPen(_MAGENTA_LEG_BORDER, 1))
        painter.drawRoundedRect(int(x), int(by), int(bw), int(bh), 4, 4)
        painter.setPen(_TEXT_DIM)
        label = f"{format_date(rng.start)} ~ {format_date(rng.end)}"
        painter.drawText(int(x) + 6, int(by), int(bw) - 8, int(bh), Qt.AlignVCenter | Qt.AlignLeft, label)

    def _paint_test_bar(self, painter, row: GanttRow, row_index: int, y: int, h: int):
        node = row.node
        if node is None:
            return
        rng = node_range(node)
        if not rng:
            painter.setPen(_UNSCHEDULED)
            painter.drawText(8, y, 120, h, Qt.AlignVCenter | Qt.AlignLeft, "未排期")
            return

        x, by, bw, bh = self._bar_rect(row_index, rng)
        is_overlap = id(node) in self._view.overlap_node_ids
        if is_overlap:
            rect_color = _OVERLAP_DIM if row_index == self._view.hover_row else _OVERLAP
            border = _OVERLAP
        else:
            rect_color = _MAGENTA_DIM if row_index == self._view.hover_row else _MAGENTA
            border = _MAGENTA
        painter.setBrush(rect_color)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(int(x), int(by), int(bw), int(bh), 4, 4)
        painter.setPen(_TEXT)
        label = f"{format_date(rng.start)} ~ {format_date(rng.end)}"
        painter.drawText(int(x) + 6, int(by), int(bw) - 8, int(bh), Qt.AlignVCenter | Qt.AlignLeft, label)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        row_index = self._view.row_at(pos.y())
        if row_index != self._view.hover_row:
            self._view.hover_row = row_index
            self.hover_changed.emit(row_index)
            self.update()

        if self._drag_mode == DragMode.PAN:
            delta = pos - self._pan_anchor
            h_bar = self._scroll_area.horizontalScrollBar()
            v_bar = self._scroll_area.verticalScrollBar()
            new_h = self._pan_scroll[0] - delta.x()
            if delta.x() < 0 and new_h >= h_bar.maximum():
                added = self._view.visible_days()
                if self._view.extend_axis_end(added):
                    self.rebuild_metrics(self._scroll_area.viewport().width())
            h_bar.setValue(new_h)
            v_bar.setValue(self._pan_scroll[1] - delta.y())
            return

        if self._drag_mode in (
            DragMode.MOVE,
            DragMode.MOVE_LEG,
            DragMode.RESIZE_START,
            DragMode.RESIZE_END,
            DragMode.CREATE,
        ):
            self._apply_drag(pos)
            self.update()
            return

        _, mode = self._hit_test_bar(pos)
        if mode in (DragMode.MOVE, DragMode.MOVE_LEG):
            self.setCursor(Qt.SizeAllCursor)
        elif mode in (DragMode.RESIZE_START, DragMode.RESIZE_END):
            self.setCursor(Qt.SizeHorCursor)
        elif mode == DragMode.CREATE:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        if event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._drag_mode = DragMode.PAN
            self._pan_anchor = pos
            h = self._scroll_area.horizontalScrollBar().value()
            v = self._scroll_area.verticalScrollBar().value()
            self._pan_scroll = (h, v)
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() != Qt.LeftButton:
            return

        row_index, mode = self._hit_test_bar(pos)
        if row_index < 0 or mode == DragMode.NONE:
            return
        row = self._view.rows[row_index]
        if row.leg is None:
            return

        if mode == DragMode.MOVE_LEG:
            self._drag_mode = mode
            self._drag_leg = row.leg
            self._drag_node = None
            self._drag_snapshot = snapshot_leg_dates(row.leg)
            self._orig_leg_range = leg_range(row.leg)
            if self._orig_leg_range:
                anchor = self._view.day_at_x(pos.x())
                self._drag_start_offset = day_offset(self._orig_leg_range.start, anchor)
            self._apply_drag(pos)
            self.update()
            return

        if row.kind != "test" or row.node is None:
            return

        self._drag_mode = mode
        self._drag_leg = row.leg
        self._drag_node = row.node
        self._drag_snapshot = snapshot_leg_dates(row.leg)
        self._orig_range = node_range(row.node)
        if mode == DragMode.MOVE and self._orig_range:
            anchor = self._view.day_at_x(pos.x())
            self._drag_start_offset = day_offset(self._orig_range.start, anchor)
        if mode == DragMode.CREATE:
            self._create_anchor_day = self._view.day_at_x(pos.x())
            set_node_range(row.node, self._create_anchor_day, self._create_anchor_day)
        self._apply_drag(pos)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._drag_mode == DragMode.PAN:
            self._drag_mode = DragMode.NONE
            self.setCursor(Qt.ArrowCursor)
            return
        if self._drag_mode == DragMode.NONE:
            return

        bounds_msg = self._drag_bounds_violation()
        if bounds_msg and self._drag_leg is not None:
            restore_leg_dates(self._drag_leg, self._drag_snapshot)
            QMessageBox.warning(self, "日期无效", f"{bounds_msg}，已恢复原计划。")
        elif self._drag_leg is not None and leg_has_overlap(self._drag_leg):
            reply = QMessageBox.question(
                self, "试验重叠", "试验重叠，是否后续试验顺延？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                node_index = self._node_index(self._drag_leg, self._drag_node)
                ok = cascade_subsequent_nodes(
                    self._drag_leg, node_index, self._view.proj_start, self._view.proj_end,
                )
                if not ok or leg_has_overlap(self._drag_leg):
                    restore_leg_dates(self._drag_leg, self._drag_snapshot)
                    QMessageBox.warning(self, "无法顺延", "顺延后将超出项目检测日期范围，已恢复原计划。")
                else:
                    self.schedule_changed.emit()
            else:
                restore_leg_dates(self._drag_leg, self._drag_snapshot)
        else:
            self.schedule_changed.emit()

        self._drag_mode = DragMode.NONE
        self._drag_leg = None
        self._drag_node = None
        self._drag_snapshot = {}
        self._orig_range = None
        self._orig_leg_range = None
        self._create_anchor_day = None
        self._intended_range = None
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def _drag_bounds_violation(self) -> Optional[str]:
        if self._intended_range is None or not self._intended_range.is_valid():
            return None
        return range_exceeds_project_bounds(
            self._intended_range.start,
            self._intended_range.end,
            self._view.proj_start,
            self._view.proj_end,
        )

    def _node_index(self, leg: TestLeg, node: Optional[TestNode]) -> int:
        if node is None:
            return -1
        for i, item in enumerate(leg.nodes or []):
            if item is node:
                return i
        return -1

    def _apply_drag(self, pos: QPoint):
        if self._drag_mode == DragMode.MOVE_LEG:
            if self._drag_leg is None or self._orig_leg_range is None:
                return
            restore_leg_dates(self._drag_leg, self._drag_snapshot)
            anchor = self._view.day_at_x(pos.x())
            new_start = anchor.addDays(-self._drag_start_offset)
            delta = self._orig_leg_range.start.daysTo(new_start)
            duration = self._orig_leg_range.days() - 1
            intended_start = self._orig_leg_range.start.addDays(delta)
            intended_end = intended_start.addDays(duration)
            self._intended_range = DateRange(intended_start, intended_end)
            shift_scheduled_nodes(
                self._drag_leg, delta, self._view.proj_start, self._view.proj_end,
            )
            return

        if self._drag_node is None:
            return
        day = self._view.day_at_x(pos.x())
        if self._drag_mode == DragMode.CREATE and self._create_anchor_day is not None:
            start = min(self._create_anchor_day, day)
            end = max(self._create_anchor_day, day)
            if start.daysTo(end) + 1 < MIN_BAR_DAYS:
                end = start
            self._intended_range = DateRange(start, end)
            clamped = clamp_range(start, end, self._view.proj_start, self._view.proj_end)
            if clamped:
                set_node_range(self._drag_node, clamped.start, clamped.end)
            return

        current = node_range(self._drag_node)
        if not current and self._orig_range:
            current = self._orig_range
        if not current:
            return

        if self._drag_mode == DragMode.MOVE:
            if self._orig_range is None:
                return
            anchor = self._view.day_at_x(pos.x())
            new_start = anchor.addDays(-self._drag_start_offset)
            duration = self._orig_range.days() - 1
            new_end = new_start.addDays(duration)
            self._intended_range = DateRange(new_start, new_end)
            clamped = clamp_range(new_start, new_end, self._view.proj_start, self._view.proj_end)
            if clamped:
                set_node_range(self._drag_node, clamped.start, clamped.end)
        elif self._drag_mode == DragMode.RESIZE_START:
            if self._orig_range is None:
                return
            self._intended_range = DateRange(day, self._orig_range.end)
            clamped = clamp_resize_start(
                day, self._orig_range.end, self._view.proj_start, self._view.proj_end,
            )
            if clamped and clamped.days() >= MIN_BAR_DAYS:
                set_node_range(self._drag_node, clamped.start, clamped.end)
        elif self._drag_mode == DragMode.RESIZE_END:
            if self._orig_range is None:
                return
            self._intended_range = DateRange(self._orig_range.start, day)
            clamped = clamp_resize_end(
                self._orig_range.start, day, self._view.proj_start, self._view.proj_end,
            )
            if clamped and clamped.days() >= MIN_BAR_DAYS:
                set_node_range(self._drag_node, clamped.start, clamped.end)


class GanttChartWidget(QWidget):
    """Scrollable Gantt view with a frozen label column."""

    schedule_changed = Signal()

    def __init__(self, state: ProjectState, parent=None):
        super().__init__(parent)
        self._project_state = state
        self._view = GanttViewState(state)
        self._zoom_index = DEFAULT_ZOOM_INDEX
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(False)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setFrameShape(QScrollArea.NoFrame)
        self.left_scroll.setFixedWidth(LEFT_COL_WIDTH)
        self.left_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.left_panel = GanttLeftPanel(self._view)
        self.left_scroll.setWidget(self.left_panel)

        self.timeline = GanttTimelinePanel(self._view, self.scroll_area)
        self.timeline.schedule_changed.connect(self.schedule_changed.emit)
        self.scroll_area.setWidget(self.timeline)

        root.addWidget(self.left_scroll)
        root.addWidget(self.scroll_area, stretch=1)

        vbar = self.scroll_area.verticalScrollBar()
        vbar.valueChanged.connect(self.left_scroll.verticalScrollBar().setValue)
        self.scroll_area.horizontalScrollBar().actionTriggered.connect(self._extend_on_scroll_action)
        self.left_panel.hover_changed.connect(lambda _: self.timeline.update())
        self.timeline.hover_changed.connect(lambda _: self.left_panel.update())

    @property
    def state(self) -> ProjectState:
        return self._project_state

    @state.setter
    def state(self, value: ProjectState) -> None:
        self._project_state = value
        self._view.project_state = value
        self._view.extra_future_days = 0

    @property
    def canvas(self):
        """Backward-compatible alias used by tests."""
        return self.timeline

    def refresh(self) -> None:
        self._view.zoom_index = self._zoom_index
        self._view.refresh()
        QTimer.singleShot(0, self._finalize_layout)

    def warn_if_overlaps(self) -> bool:
        """Show a warning when the project already has overlapping schedules."""
        from src.ui.gantt_utils import format_overlap_warning, project_overlapping_legs

        if not project_overlapping_legs(self._project_state):
            return False
        detail = format_overlap_warning(self._project_state)
        QMessageBox.warning(
            self,
            "试验重叠",
            "当前项目存在日期重叠的试验，重叠项已用橙色标记。\n\n" + detail,
        )
        return True

    def _extend_on_scroll_action(self, action: int) -> None:
        """Grow the axis when the user tries to scroll past the right edge."""
        if action not in (
            QAbstractSlider.SliderSingleStepAdd,
            QAbstractSlider.SliderPageStepAdd,
        ):
            return
        bar = self.scroll_area.horizontalScrollBar()
        if bar.maximum() <= 0:
            return
        pending = bar.sliderPosition()
        if pending < bar.maximum():
            return
        keep = bar.value()
        if not self._view.extend_axis_end(self._view.visible_days()):
            return
        self.timeline.rebuild_metrics(max(self.scroll_area.viewport().width(), 320))
        bar.setValue(keep)

    def _finalize_layout(self) -> None:
        viewport_w = max(self.scroll_area.viewport().width(), 320)
        self.timeline.rebuild_metrics(viewport_w)
        self.left_panel.refresh_geometry()
        self.left_scroll.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().value())

    def set_zoom_index(self, index: int) -> None:
        self._zoom_index = max(0, min(index, len(ZOOM_LEVELS) - 1))

    def zoom_step(self, delta: int) -> None:
        self.set_zoom_index(self._zoom_index + delta)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._finalize_layout()

