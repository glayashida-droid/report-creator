"""Pure helpers for the Leg Gantt chart (dates, overlap, cascade, labels)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QDate

from src.models.project_state import ProjectState, TestLeg, TestNode

ZOOM_LEVELS = (7, 14, 21, 30)  # days visible in viewport: 1 week … 1 month
DEFAULT_ZOOM_INDEX = 1  # 14 days
AXIS_LOOKBACK_DAYS = 7
AXIS_PAD_DAYS = 2


@dataclass(frozen=True)
class DateRange:
    start: QDate
    end: QDate

    def is_valid(self) -> bool:
        return self.start.isValid() and self.end.isValid() and self.start <= self.end

    def days(self) -> int:
        if not self.is_valid():
            return 0
        return self.start.daysTo(self.end) + 1


def parse_date(value: Optional[str]) -> QDate:
    if not value:
        return QDate()
    parsed = QDate.fromString(str(value).strip(), "yyyy-MM-dd")
    return parsed if parsed.isValid() else QDate()


def format_date(value: QDate) -> str:
    if not value.isValid():
        return ""
    return value.toString("yyyy-MM-dd")


def node_range(node: TestNode) -> Optional[DateRange]:
    start = parse_date(node.start_date)
    end = parse_date(node.end_date)
    if not start.isValid() or not end.isValid() or start > end:
        return None
    return DateRange(start, end)


def node_has_schedule(node: TestNode) -> bool:
    return node_range(node) is not None


def equipment_tooltip(node: TestNode) -> str:
    items = list(node.equipments or [])
    if items:
        lines = []
        for eq in items:
            parts = [p for p in (eq.code, eq.name) if p and str(p).strip()]
            if eq.model and str(eq.model).strip():
                parts.append(f"({eq.model})")
            lines.append(" ".join(parts) if parts else "/")
        return "\n".join(lines)
    legacy = (node.equipment_name or "").strip()
    if legacy:
        return legacy
    return "（未选择设备）"


def test_label(node: TestNode) -> str:
    name = (node.test_name or "").strip()
    return name or "（未命名试验）"


def ranges_overlap(a: DateRange, b: DateRange) -> bool:
    """Two date ranges overlap only when they share at least one interior day.
    Ranges that merely touch at a single endpoint (end == other.start) are
    considered adjacent, not overlapping, so back-to-back schedules are allowed.
    """
    return a.start < b.end and b.start < a.end


def find_overlaps_in_leg(leg: TestLeg, ignore_node: Optional[TestNode] = None) -> List[Tuple[TestNode, TestNode]]:
    """Return pairs of scheduled nodes in leg order that overlap."""
    scheduled: List[Tuple[TestNode, DateRange]] = []
    for node in leg.nodes or []:
        if ignore_node is not None and node is ignore_node:
            continue
        rng = node_range(node)
        if rng:
            scheduled.append((node, rng))

    overlaps: List[Tuple[TestNode, TestNode]] = []
    for i, (node_a, rng_a) in enumerate(scheduled):
        for node_b, rng_b in scheduled[i + 1 :]:
            if ranges_overlap(rng_a, rng_b):
                overlaps.append((node_a, node_b))
    return overlaps


def leg_has_overlap(leg: TestLeg) -> bool:
    return bool(find_overlaps_in_leg(leg))


def find_leg_for_node(state: ProjectState, node: TestNode) -> Optional[TestLeg]:
    for leg in state.legs or []:
        for item in leg.nodes or []:
            if item is node:
                return leg
    return None


def node_index_in_leg(leg: TestLeg, node: TestNode) -> int:
    for i, item in enumerate(leg.nodes or []):
        if item is node:
            return i
    return -1


def overlapped_node_ids_in_leg(leg: TestLeg) -> set[int]:
    ids: set[int] = set()
    for node_a, node_b in find_overlaps_in_leg(leg):
        ids.add(id(node_a))
        ids.add(id(node_b))
    return ids


def would_node_overlap_in_leg(
    leg: TestLeg,
    node: TestNode,
    start: QDate,
    end: QDate,
) -> bool:
    proposed = DateRange(start, end)
    if not proposed.is_valid():
        return False
    for other in leg.nodes or []:
        if other is node:
            continue
        other_rng = node_range(other)
        if other_rng and ranges_overlap(proposed, other_rng):
            return True
    return False


def project_overlapping_legs(state: ProjectState) -> List[TestLeg]:
    return [leg for leg in (state.legs or []) if leg_has_overlap(leg)]


def format_overlap_warning(state: ProjectState) -> str:
    lines: List[str] = []
    for leg in project_overlapping_legs(state):
        leg_label = leg.leg_name or leg.leg_id or "Leg"
        seen: set[tuple[str, str]] = set()
        for node_a, node_b in find_overlaps_in_leg(leg):
            key = tuple(sorted((test_label(node_a), test_label(node_b))))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"{leg_label}：{key[0]} 与 {key[1]} 日期重叠")
    return "\n".join(lines)


def snapshot_leg_dates(leg: TestLeg) -> dict[int, Tuple[Optional[str], Optional[str]]]:
    return {id(node): (node.start_date, node.end_date) for node in (leg.nodes or [])}


def leg_range(leg: TestLeg) -> Optional[DateRange]:
    """Envelope from the earliest scheduled start to the latest scheduled end."""
    starts: List[QDate] = []
    ends: List[QDate] = []
    for node in leg.nodes or []:
        rng = node_range(node)
        if rng:
            starts.append(rng.start)
            ends.append(rng.end)
    if not starts:
        return None
    return DateRange(
        min(starts, key=lambda d: d.toJulianDay()),
        max(ends, key=lambda d: d.toJulianDay()),
    )


def shift_scheduled_nodes(
    leg: TestLeg,
    delta_days: int,
    proj_start: QDate,
    proj_end: QDate,
) -> int:
    """Move every scheduled node by the same day offset.

    Duration of each test is unchanged. The offset is shortened if the
    envelope would leave the project date window. Unscheduled nodes are left
    alone. Returns the delta that was actually applied.
    """
    envelope = leg_range(leg)
    if envelope is None or delta_days == 0:
        return 0
    clamped = clamp_range(
        envelope.start.addDays(delta_days),
        envelope.end.addDays(delta_days),
        proj_start,
        proj_end,
    )
    if clamped is None:
        return 0
    applied = envelope.start.daysTo(clamped.start)
    if applied == 0:
        return 0
    for node in leg.nodes or []:
        rng = node_range(node)
        if rng:
            set_node_range(node, rng.start.addDays(applied), rng.end.addDays(applied))
    return applied


def restore_leg_dates(leg: TestLeg, snapshot: dict[int, Tuple[Optional[str], Optional[str]]]) -> None:
    for node in leg.nodes or []:
        if id(node) in snapshot:
            start, end = snapshot[id(node)]
            node.start_date = start
            node.end_date = end


def clamp_range(
    start: QDate,
    end: QDate,
    proj_start: QDate,
    proj_end: QDate,
) -> Optional[DateRange]:
    if not start.isValid() or not end.isValid():
        return None
    if start > end:
        end = start

    duration = start.daysTo(end)

    if proj_start.isValid() and start < proj_start:
        start = proj_start
        end = start.addDays(duration)
    if proj_end.isValid() and end > proj_end:
        end = proj_end
        start = end.addDays(-duration)
    if proj_start.isValid() and start < proj_start:
        start = proj_start
    if proj_end.isValid() and end > proj_end:
        end = proj_end
    if start > end:
        return None
    return DateRange(start, end)


def set_node_range(node: TestNode, start: QDate, end: QDate) -> None:
    node.start_date = format_date(start)
    node.end_date = format_date(end)


def cascade_subsequent_nodes(
    leg: TestLeg,
    from_index: int,
    proj_start: QDate,
    proj_end: QDate,
) -> bool:
    """
    Push nodes after from_index forward so none overlap predecessors.
    Returns False if cascade would violate project bounds.
    """
    nodes = list(leg.nodes or [])
    if from_index < 0 or from_index >= len(nodes):
        return True

    for i in range(from_index + 1, len(nodes)):
        prev = nodes[i - 1]
        curr = nodes[i]
        prev_rng = node_range(prev)
        curr_rng = node_range(curr)
        if not prev_rng or not curr_rng:
            continue
        if curr_rng.start > prev_rng.end:
            continue
        duration = curr_rng.days() - 1
        new_start = prev_rng.end.addDays(1)
        new_end = new_start.addDays(duration)
        clamped = clamp_range(new_start, new_end, proj_start, proj_end)
        if clamped is None:
            return False
        set_node_range(curr, clamped.start, clamped.end)
        # Re-run cascade on this node if it now overlaps its successor
        if i < len(nodes) - 1:
            next_rng = node_range(nodes[i + 1])
            if next_rng and clamped.end >= next_rng.start:
                # continue loop naturally
                pass
    return True


def compute_axis_range(
    legs: Sequence[TestLeg],
    proj_start: QDate,
    proj_end: QDate,
    fallback_start: QDate,
    fallback_visible_days: int,
) -> DateRange:
    starts: List[QDate] = []
    ends: List[QDate] = []
    for leg in legs or []:
        for node in leg.nodes or []:
            rng = node_range(node)
            if rng:
                starts.append(rng.start)
                ends.append(rng.end)

    if proj_start.isValid():
        starts.append(proj_start)
    if proj_end.isValid():
        ends.append(proj_end)
    if fallback_start.isValid():
        starts.append(fallback_start)
        ends.append(fallback_start)

    if starts and ends:
        axis_start = min(starts, key=lambda d: d.toJulianDay())
        axis_end = max(ends, key=lambda d: d.toJulianDay())
    else:
        axis_start = fallback_start if fallback_start.isValid() else QDate.currentDate()
        axis_end = axis_start.addDays(max(fallback_visible_days - 1, 0))

    axis_start = axis_start.addDays(-AXIS_LOOKBACK_DAYS)
    # Keep at least one viewport of empty future so the chart can be panned
    # past the last scheduled day (otherwise the scrollbar pins at that date).
    forward = max(AXIS_PAD_DAYS, fallback_visible_days)
    axis_end = axis_end.addDays(forward)
    if axis_start > axis_end:
        axis_end = axis_start.addDays(max(fallback_visible_days - 1, 0))
    return DateRange(axis_start, axis_end)


def qdate_to_py(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def py_to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def iter_month_ticks(axis: DateRange) -> Iterable[Tuple[QDate, str]]:
    if not axis.is_valid():
        return
    cursor = qdate_to_py(axis.start)
    end = qdate_to_py(axis.end)
    cursor = date(cursor.year, cursor.month, 1)
    if cursor < qdate_to_py(axis.start):
        pass
    while cursor <= end:
        yield py_to_qdate(cursor), f"{cursor.month}月"
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)


def day_offset(axis_start: QDate, day: QDate) -> int:
    return axis_start.daysTo(day)
