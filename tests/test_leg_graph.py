import sys

from PySide6.QtCore import QDate, QPoint
from PySide6.QtWidgets import QApplication, QComboBox

from src.models.project_state import ProjectState, TestLeg, TestNode
from src.ui.leg_graph import CUSTOM_TEST, PLACEHOLDER_TEST, LegGraphArea, fill_test_combo
from src.ui.gantt_chart import LEG_BAR_HEIGHT, DragMode, GanttChartWidget
from src.ui.gantt_utils import leg_range, node_range


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_reloaded_nodes_get_db_loader():
    _app()
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="随机振动"), TestNode(test_name="绝缘电阻")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    nodes = area.leg_widgets[0].node_widgets
    assert len(nodes) == 2
    assert nodes[0].db_loader is area.db_loader
    assert nodes[1].db_loader is area.db_loader


def test_added_nodes_get_db_loader():
    _app()
    state = ProjectState(project_id="P1")
    area = LegGraphArea(state)
    area.add_leg()
    area.leg_widgets[0].on_add_node()
    assert area.leg_widgets[0].node_widgets[0].db_loader is area.db_loader


def test_combo_includes_custom_and_keeps_typed_name():
    _app()
    combo = QComboBox()
    combo.setEditable(True)
    fill_test_combo(combo, ["振动", "机械冲击"], "盐雾")
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert texts[0] == PLACEHOLDER_TEST
    assert "振动" in texts
    assert "机械冲击" in texts
    assert "盐雾" in texts
    assert texts[-1] == CUSTOM_TEST
    assert combo.currentText() == "盐雾"
    fill_test_combo(combo, ["振动"], CUSTOM_TEST)
    assert combo.currentText() == ""
    assert combo.itemText(combo.count() - 1) == CUSTOM_TEST


def test_gantt_follows_state_reassignment():
    _app()
    initial = ProjectState(project_id="P1")
    area = LegGraphArea(initial)
    loaded = ProjectState(
        project_id="P2",
        test_start_date="2026-08-19",
        test_end_date="2027-02-05",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="机械冲击", start_date="2026-09-01", end_date="2026-09-07"),
                    TestNode(test_name="湿热循环"),
                ],
            )
        ],
    )
    area.state = loaded
    area.set_gantt_mode(True)
    area.gantt_chart.refresh()
    view = area.gantt_chart._view
    assert view.project_state is loaded
    assert len(view.rows) == 3  # leg header + 2 tests
    assert view.rows[1].label == "机械冲击"


def test_gantt_marks_overlapping_nodes():
    _app()
    node_a = TestNode(test_name="湿热循环", start_date="2026-08-20", end_date="2026-08-22")
    node_b = TestNode(test_name="盐雾腐蚀", start_date="2026-08-19", end_date="2026-08-28")
    state = ProjectState(
        project_id="P1",
        legs=[TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[node_a, node_b])],
    )
    chart = GanttChartWidget(state)
    chart.refresh()
    assert len(chart._view.overlap_node_ids) == 2


def test_gantt_leg_bar_is_move_only():
    _app()
    state = ProjectState(
        project_id="P1",
        test_start_date="2026-08-19",
        test_end_date="2026-08-31",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="振动", start_date="2026-08-19", end_date="2026-08-21"),
                    TestNode(test_name="机械冲击", start_date="2026-08-22", end_date="2026-08-26"),
                ],
            )
        ],
    )
    chart = GanttChartWidget(state)
    chart._view.refresh()
    chart.timeline.rebuild_metrics(420)
    rng = leg_range(state.legs[0])
    assert rng is not None
    x, y, w, h = chart.timeline._bar_rect(0, rng, LEG_BAR_HEIGHT)
    _, mode_mid = chart.timeline._hit_test_bar(QPoint(int(x + w / 2), int(y + h / 2)))
    _, mode_left = chart.timeline._hit_test_bar(QPoint(int(x + 2), int(y + h / 2)))
    assert mode_mid == DragMode.MOVE_LEG
    assert mode_left == DragMode.MOVE_LEG


def test_gantt_scheduled_row_miss_does_not_create():
    _app()
    second = TestNode(test_name="机械冲击", start_date="2026-08-22", end_date="2026-08-26")
    state = ProjectState(
        project_id="P1",
        test_start_date="2026-08-19",
        test_end_date="2026-08-31",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="振动", start_date="2026-08-19", end_date="2026-08-21"),
                    second,
                ],
            )
        ],
    )
    chart = GanttChartWidget(state)
    chart._view.refresh()
    chart.timeline.rebuild_metrics(420)
    assert chart._view.rows[2].node is second
    rng = node_range(second)
    assert rng is not None
    x, y, w, h = chart.timeline._bar_rect(2, rng)
    row_top = chart._view.row_top(2)
    miss = QPoint(max(0, int(x) - 20), int(row_top + h))
    _, mode_miss = chart.timeline._hit_test_bar(miss)
    assert mode_miss == DragMode.NONE
    _, mode_pad = chart.timeline._hit_test_bar(QPoint(int(x + w / 2), int(row_top + 1)))
    assert mode_pad == DragMode.MOVE
    empty = TestNode(test_name="未排期")
    state.legs[0].nodes.append(empty)
    chart._view.refresh()
    chart.timeline.rebuild_metrics(420)
    empty_row = next(i for i, row in enumerate(chart._view.rows) if row.node is empty)
    empty_y = chart._view.row_top(empty_row) + 8
    _, mode_empty = chart.timeline._hit_test_bar(QPoint(40, empty_y))
    assert mode_empty == DragMode.CREATE


def test_gantt_axis_extends_past_last_bar():
    _app()
    state = ProjectState(
        project_id="P1",
        test_start_date="2026-08-19",
        test_end_date="2026-08-28",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="振动", start_date="2026-08-19", end_date="2026-08-19"),
                    TestNode(test_name="机械冲击", start_date="2026-08-19", end_date="2026-08-26"),
                ],
            )
        ],
    )
    chart = GanttChartWidget(state)
    chart._view.refresh()
    assert chart._view.axis.end >= QDate(2026, 9, 11)
    before = chart._view.axis.end
    assert chart._view.extend_axis_end(14)
    assert chart._view.axis.end == before.addDays(14)


if __name__ == "__main__":
    test_reloaded_nodes_get_db_loader()
    test_added_nodes_get_db_loader()
    test_combo_includes_custom_and_keeps_typed_name()
    test_gantt_follows_state_reassignment()
    test_gantt_marks_overlapping_nodes()
    test_gantt_leg_bar_is_move_only()
    test_gantt_scheduled_row_miss_does_not_create()
    test_gantt_axis_extends_past_last_bar()
    print("test_leg_graph: ok")
