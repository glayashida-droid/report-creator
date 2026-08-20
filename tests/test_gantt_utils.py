"""Tests for Gantt chart helpers."""

from PySide6.QtCore import QDate

from src.models.project_state import ProjectState, TestLeg, TestNode
from src.ui.gantt_utils import (
    DateRange,
    cascade_subsequent_nodes,
    clamp_range,
    compute_axis_range,
    equipment_tooltip,
    find_leg_for_node,
    find_overlaps_in_leg,
    format_overlap_warning,
    leg_has_overlap,
    leg_range,
    node_range,
    overlapped_node_ids_in_leg,
    parse_date,
    ranges_overlap,
    restore_leg_dates,
    set_node_range,
    shift_scheduled_nodes,
    snapshot_leg_dates,
    would_node_overlap_in_leg,
)


def test_ranges_overlap_exclusive_endpoints():
    a = DateRange(QDate(2026, 8, 1), QDate(2026, 8, 5))
    # Adjacent (touching at endpoint) is NOT overlap
    b = DateRange(QDate(2026, 8, 5), QDate(2026, 8, 10))
    assert not ranges_overlap(a, b)
    # One day gap is also not overlap
    c = DateRange(QDate(2026, 8, 6), QDate(2026, 8, 10))
    assert not ranges_overlap(a, c)
    # Actual interior overlap
    d = DateRange(QDate(2026, 8, 4), QDate(2026, 8, 8))
    assert ranges_overlap(a, d)


def test_clamp_range_respects_project_bounds():
    proj_start = QDate(2026, 8, 1)
    proj_end = QDate(2026, 8, 31)
    clamped = clamp_range(QDate(2026, 7, 20), QDate(2026, 8, 10), proj_start, proj_end)
    assert clamped is not None
    assert clamped.start == proj_start
    assert clamped.end == QDate(2026, 8, 22)


def test_overlap_detection_in_leg():
    leg = TestLeg(
        leg_id="L1",
        leg_name="Leg 1",
        nodes=[
            TestNode(test_name="A", start_date="2026-08-01", end_date="2026-08-05"),
            TestNode(test_name="B", start_date="2026-08-04", end_date="2026-08-08"),
        ],
    )
    assert leg_has_overlap(leg)
    assert len(find_overlaps_in_leg(leg)) == 1
    overlap_ids = overlapped_node_ids_in_leg(leg)
    assert len(overlap_ids) == 2


def test_would_node_overlap_in_leg():
    leg = TestLeg(
        leg_id="L1",
        leg_name="Leg 1",
        nodes=[
            TestNode(test_name="A", start_date="2026-08-01", end_date="2026-08-05"),
            TestNode(test_name="B", start_date="2026-08-10", end_date="2026-08-12"),
        ],
    )
    assert would_node_overlap_in_leg(
        leg, leg.nodes[1], QDate(2026, 8, 4), QDate(2026, 8, 8)
    )
    assert not would_node_overlap_in_leg(
        leg, leg.nodes[1], QDate(2026, 8, 6), QDate(2026, 8, 9)
    )


def test_find_leg_for_node_and_format_warning():
    node_a = TestNode(test_name="湿热循环", start_date="2026-08-20", end_date="2026-08-22")
    node_b = TestNode(test_name="盐雾腐蚀", start_date="2026-08-19", end_date="2026-08-28")
    leg = TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[node_a, node_b])
    state = ProjectState(project_id="P1", legs=[leg])
    assert find_leg_for_node(state, node_a) is leg
    assert leg_has_overlap(leg)
    warning = format_overlap_warning(state)
    assert "Leg 1" in warning
    assert "湿热循环" in warning
    assert "盐雾腐蚀" in warning


def test_cascade_pushes_subsequent_nodes():
    leg = TestLeg(
        leg_id="L1",
        leg_name="Leg 1",
        nodes=[
            TestNode(test_name="A", start_date="2026-08-01", end_date="2026-08-05"),
            TestNode(test_name="B", start_date="2026-08-04", end_date="2026-08-08"),
            TestNode(test_name="C", start_date="2026-08-09", end_date="2026-08-12"),
        ],
    )
    set_node_range(leg.nodes[0], QDate(2026, 8, 1), QDate(2026, 8, 7))
    assert leg_has_overlap(leg)
    ok = cascade_subsequent_nodes(leg, 0, QDate(2026, 8, 1), QDate(2026, 9, 30))
    assert ok
    assert not leg_has_overlap(leg)
    assert leg.nodes[1].start_date == "2026-08-08"
    assert leg.nodes[1].end_date == "2026-08-12"
    assert leg.nodes[2].start_date == "2026-08-13"
    assert leg.nodes[2].end_date == "2026-08-16"


def test_snapshot_restore():
    leg = TestLeg(
        leg_id="L1",
        leg_name="Leg 1",
        nodes=[TestNode(test_name="A", start_date="2026-08-01", end_date="2026-08-03")],
    )
    snap = snapshot_leg_dates(leg)
    set_node_range(leg.nodes[0], QDate(2026, 8, 10), QDate(2026, 8, 12))
    restore_leg_dates(leg, snap)
    assert leg.nodes[0].start_date == "2026-08-01"
    assert leg.nodes[0].end_date == "2026-08-03"


def test_compute_axis_when_all_unscheduled():
    leg = TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[TestNode(test_name="A")])
    axis = compute_axis_range([leg], QDate(), QDate(), QDate(2026, 8, 19), 14)
    assert axis.is_valid()
    assert axis.start <= QDate(2026, 8, 19)


def test_compute_axis_looks_back_a_week_past_project_start():
    today = QDate(2026, 8, 19)
    axis = compute_axis_range([], today, QDate(2026, 8, 31), today, 14)
    assert axis.start == today.addDays(-7)
    assert axis.end >= today


def test_compute_axis_keeps_a_viewport_of_future():
    today = QDate(2026, 8, 19)
    last = QDate(2026, 8, 26)
    leg = TestLeg(
        leg_id="L1",
        leg_name="Leg 1",
        nodes=[TestNode(test_name="机械冲击", start_date="2026-08-19", end_date="2026-08-26")],
    )
    axis = compute_axis_range([leg], today, QDate(2026, 8, 28), today, 14)
    assert axis.end >= last.addDays(14)
    assert axis.end >= QDate(2026, 8, 28).addDays(14)


def test_leg_range_envelope_ignores_unscheduled():
    leg = TestLeg(
        leg_id="L1",
        leg_name="Leg 1",
        nodes=[
            TestNode(test_name="振动", start_date="2026-08-19", end_date="2026-08-21"),
            TestNode(test_name="未排期"),
            TestNode(test_name="机械冲击", start_date="2026-08-22", end_date="2026-08-26"),
        ],
    )
    envelope = leg_range(leg)
    assert envelope is not None
    assert envelope.start == QDate(2026, 8, 19)
    assert envelope.end == QDate(2026, 8, 26)
    assert leg_range(TestLeg(leg_id="L2", leg_name="Leg 2", nodes=[TestNode(test_name="空")])) is None


def test_shift_scheduled_nodes_keeps_durations_and_gaps():
    leg = TestLeg(
        leg_id="L1",
        leg_name="Leg 1",
        nodes=[
            TestNode(test_name="A", start_date="2026-08-19", end_date="2026-08-21"),
            TestNode(test_name="空"),
            TestNode(test_name="B", start_date="2026-08-22", end_date="2026-08-26"),
        ],
    )
    applied = shift_scheduled_nodes(leg, 3, QDate(2026, 8, 1), QDate(2026, 9, 30))
    assert applied == 3
    assert leg.nodes[0].start_date == "2026-08-22"
    assert leg.nodes[0].end_date == "2026-08-24"
    assert leg.nodes[1].start_date is None
    assert leg.nodes[2].start_date == "2026-08-25"
    assert leg.nodes[2].end_date == "2026-08-29"


def test_shift_scheduled_nodes_clamps_to_project_window():
    leg = TestLeg(
        leg_id="L1",
        leg_name="Leg 1",
        nodes=[
            TestNode(test_name="A", start_date="2026-08-19", end_date="2026-08-21"),
            TestNode(test_name="B", start_date="2026-08-22", end_date="2026-08-26"),
        ],
    )
    applied = shift_scheduled_nodes(leg, -10, QDate(2026, 8, 19), QDate(2026, 8, 31))
    assert applied == 0
    assert leg.nodes[0].start_date == "2026-08-19"
    applied = shift_scheduled_nodes(leg, 20, QDate(2026, 8, 19), QDate(2026, 8, 31))
    assert applied == 5  # envelope 19-26 shifted to 24-31
    assert leg.nodes[0].start_date == "2026-08-24"
    assert leg.nodes[1].end_date == "2026-08-31"


def test_equipment_tooltip():
    node = TestNode(test_name="振动", equipment_name="SHAED-A050 冲击台")
    assert "SHAED-A050" in equipment_tooltip(node)
    empty = TestNode(test_name="振动")
    assert "未选择设备" in equipment_tooltip(empty)


def test_node_range_invalid():
    node = TestNode(test_name="A", start_date="2026-08-10", end_date="2026-08-01")
    assert node_range(node) is None
    assert parse_date("bad") == QDate()


if __name__ == "__main__":
    test_ranges_overlap_exclusive_endpoints()
    test_clamp_range_respects_project_bounds()
    test_overlap_detection_in_leg()
    test_would_node_overlap_in_leg()
    test_find_leg_for_node_and_format_warning()
    test_cascade_pushes_subsequent_nodes()
    test_snapshot_restore()
    test_compute_axis_when_all_unscheduled()
    test_compute_axis_looks_back_a_week_past_project_start()
    test_compute_axis_keeps_a_viewport_of_future()
    test_leg_range_envelope_ignores_unscheduled()
    test_shift_scheduled_nodes_keeps_durations_and_gaps()
    test_shift_scheduled_nodes_clamps_to_project_window()
    test_equipment_tooltip()
    test_node_range_invalid()
    print("test_gantt_utils: ok")
