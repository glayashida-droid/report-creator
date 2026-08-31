import sys
from unittest.mock import patch

from PySide6.QtCore import QDate, QPoint
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox

from src.io.test_photos import test_dir_key as leg_test_dir_key
from src.models.project_state import ProjectState, TestEquipment, TestLeg, TestNode, TestResult, TestSample, TestStandard
from src.ui.leg_graph import (
    LEG_CARD_WIDTH,
    PLACEHOLDER_TEST,
    LegGraphArea,
    fill_test_combo,
    insert_index_for_y,
)
from src.ui.gantt_chart import LEG_BAR_HEIGHT, DragMode, GanttChartWidget
from src.ui.gantt_utils import leg_range, node_range


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _test_dir(root, leg_name: str, test_name: str):
    return root / "3.测试组" / leg_test_dir_key(leg_name, test_name)


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


def test_detail_button_disabled_until_test_name():
    _app()
    state = ProjectState(
        project_id="P1",
        legs=[TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[TestNode(test_name="")])],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    nw = area.leg_widgets[0].node_widgets[0]
    assert not nw.btn_detail.isEnabled()
    assert nw.btn_detail.toolTip() == "请先选择或输入试验名称"

    nw._commit_test_name("机械冲击")
    assert nw.btn_detail.isEnabled()
    assert nw.btn_detail.toolTip() == ""


def test_detail_button_enabled_for_loaded_test_name():
    _app()
    state = ProjectState(
        project_id="P1",
        legs=[TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[TestNode(test_name="随机振动")])],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    assert area.leg_widgets[0].node_widgets[0].btn_detail.isEnabled()


def test_toolbar_save_load_use_detail_labels():
    _app()
    area = LegGraphArea(ProjectState(project_id="P1"))
    assert area.btn_save.text() == "保存明细"
    assert area.btn_load_state.text() == "加载明细"


def test_combo_keeps_typed_name_without_custom_option():
    _app()
    combo = QComboBox()
    combo.setEditable(True)
    fill_test_combo(combo, ["振动", "机械冲击"], "盐雾")
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert texts[0] == PLACEHOLDER_TEST
    assert "振动" in texts
    assert "机械冲击" in texts
    assert "盐雾" in texts
    assert "自定义" not in texts
    assert combo.currentText() == "盐雾"
    fill_test_combo(combo, ["振动"], "自定义")
    assert combo.currentText() == ""
    assert "自定义" not in [combo.itemText(i) for i in range(combo.count())]


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


def test_insert_index_for_y_before_and_after_nodes():
    _app()
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="试验1"),
                    TestNode(test_name="试验2"),
                    TestNode(test_name="试验3"),
                ],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    leg.resize(260, 420)
    leg.show()
    QApplication.processEvents()
    nodes = leg.node_widgets
    top0 = nodes[0].mapTo(leg, QPoint(0, 0)).y()
    mid0 = top0 + nodes[0].height() // 2
    top2 = nodes[2].mapTo(leg, QPoint(0, 0)).y()
    mid2 = top2 + nodes[2].height() // 2
    bottom2 = top2 + nodes[2].height()
    assert insert_index_for_y(leg, nodes, mid0 - 1) == 0
    assert insert_index_for_y(leg, nodes, mid0 + 1) == 1
    assert insert_index_for_y(leg, nodes, mid2 - 1) == 2
    assert insert_index_for_y(leg, nodes, bottom2 + 4) == 3


def test_insert_node_at_middle_and_end():
    _app()
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="试验1"), TestNode(test_name="试验2")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    leg.insert_node_at(1, "振动")
    assert [n.test_name for n in leg.leg_data.nodes] == ["试验1", "振动", "试验2"]
    leg.insert_node_at(3, "湿热循环")
    assert [n.test_name for n in leg.leg_data.nodes] == ["试验1", "振动", "试验2", "湿热循环"]
    assert leg.node_widgets[1].btn_detail.isEnabled()


def test_pool_drop_insert_keeps_sibling_committed_names(tmp_path):
    _app()
    root = tmp_path / "proj"
    _test_dir(root, "Leg 1", "振动").mkdir(parents=True)
    _test_dir(root, "Leg 1", "湿热循环").mkdir(parents=True)
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        candidate_pool=["振动", "机械冲击", "湿热循环"],
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="振动"),
                    TestNode(test_name="湿热循环"),
                ],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    # Simulate combo drift that used to trigger rename → 振动 during drop.
    sibling = leg.node_widgets[1]
    sibling.combo.blockSignals(True)
    sibling.combo.setEditText("振动")
    sibling.combo.blockSignals(False)
    sibling.node_data.test_name = "振动"
    leg._insert_from_pool_drop(2, "湿热循环")
    QApplication.processEvents()
    assert [n.test_name for n in leg.leg_data.nodes] == ["振动", "湿热循环", "湿热循环"]
    assert sibling._committed_name == "湿热循环"
    assert sibling.node_data.test_name == "湿热循环"
    assert _test_dir(root, "Leg 1", "湿热循环").is_dir()
    assert _test_dir(root, "Leg 1", "振动").is_dir()


def test_node_combo_rejects_drops_so_leg_owns_before_after():
    """Editable combo must not accept chip drops (would append into the name)."""
    _app()
    state = ProjectState(
        project_id="P1",
        candidate_pool=["湿热循环盐雾腐蚀"],
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="湿热循环盐雾腐蚀")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    combo = area.leg_widgets[0].node_widgets[0].combo
    assert not combo.acceptDrops()
    assert combo.lineEdit() is not None
    assert not combo.lineEdit().acceptDrops()


def test_commit_rollback_when_target_dir_exists(tmp_path):
    """Hooked rename to an existing trial dir: rollback card name, keep source dir."""
    _app()
    root = tmp_path / "proj"
    (_test_dir(root, "Leg 1", "湿热循环") / "试验前").mkdir(parents=True)
    _test_dir(root, "Leg 1", "振动").mkdir(parents=True)
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="湿热循环")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    nw = area.leg_widgets[0].node_widgets[0]
    nw._commit_test_name("振动")
    assert nw._committed_name == "湿热循环"
    assert nw.node_data.test_name == "湿热循环"
    assert (_test_dir(root, "Leg 1", "湿热循环") / "试验前").is_dir()
    assert _test_dir(root, "Leg 1", "振动").is_dir()
    assert not (_test_dir(root, "Leg 1", "振动") / "试验前").exists()


def test_unhooked_rename_does_not_create_test_dir(tmp_path):
    _app()
    root = tmp_path / "proj"
    root.mkdir()
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="试验A")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    nw = area.leg_widgets[0].node_widgets[0]
    nw._commit_test_name("试验B")
    assert nw._committed_name == "试验B"
    assert nw.node_data.test_name == "试验B"
    assert not (root / "3.测试组").exists()


def test_standard_override_rename_follows_hooked_dir(tmp_path):
    """Same rename path as manual commit after detail save overwrites Chinese name."""
    _app()
    root = tmp_path / "proj"
    (_test_dir(root, "Leg 1", "湿热循环") / "试验前").mkdir(parents=True)
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="湿热循环")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    nw = area.leg_widgets[0].node_widgets[0]
    assert nw._rename_chinese_test_folder("湿热循环", "标准覆盖名")
    assert (_test_dir(root, "Leg 1", "标准覆盖名") / "试验前").is_dir()
    assert not _test_dir(root, "Leg 1", "湿热循环").exists()


def test_commit_skips_rename_when_sibling_still_uses_old_name(tmp_path):
    _app()
    root = tmp_path / "proj"
    (_test_dir(root, "Leg 1", "湿热循环") / "试验前").mkdir(parents=True)
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="湿热循环"),
                    TestNode(test_name="湿热循环"),
                ],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    nw = area.leg_widgets[0].node_widgets[0]
    nw._commit_test_name("盐雾腐蚀")
    assert nw._committed_name == "盐雾腐蚀"
    assert area.leg_widgets[0].node_widgets[1]._committed_name == "湿热循环"
    assert (_test_dir(root, "Leg 1", "湿热循环") / "试验前").is_dir()
    assert not _test_dir(root, "Leg 1", "盐雾腐蚀").exists()


def test_commit_rename_retargets_data_table_paths(tmp_path):
    _app()
    from src.models.project_state import DataTableRef

    root = tmp_path / "proj"
    attach = _test_dir(root, "Leg 1", "湿热循环") / "数据表附件"
    attach.mkdir(parents=True)
    xlsx = attach / "工况.xlsx"
    xlsx.write_bytes(b"PK")
    old_key = leg_test_dir_key("Leg 1", "湿热循环")
    new_key = leg_test_dir_key("Leg 1", "前湿热循环")
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(
                        test_name="湿热循环",
                        data_tables=[
                            DataTableRef(
                                title="工况.xlsx",
                                relative_path=f"3.测试组/{old_key}/数据表附件/工况.xlsx",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    nw = area.leg_widgets[0].node_widgets[0]
    nw._commit_test_name("前湿热循环")
    assert nw._committed_name == "前湿热循环"
    assert (_test_dir(root, "Leg 1", "前湿热循环") / "数据表附件" / "工况.xlsx").is_file()
    assert not _test_dir(root, "Leg 1", "湿热循环").exists()
    assert nw.node_data.data_tables[0].relative_path == (
        f"3.测试组/{new_key}/数据表附件/工况.xlsx"
    )


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


def test_leg_cards_share_fixed_width():
    _app()
    state = ProjectState(project_id="P1")
    area = LegGraphArea(state)
    area.add_leg()
    area.add_leg()
    widths = [lw.width() for lw in area.leg_widgets]
    assert all(w == LEG_CARD_WIDTH for w in widths)
    assert widths[0] == widths[1]


def test_delete_unhooked_card_removes_node_without_confirm(tmp_path):
    _app()
    root = tmp_path / "proj"
    root.mkdir()
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="未挂钩"), TestNode(test_name="保留")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    with patch.object(QMessageBox, "exec") as mock_exec:
        leg.on_node_deleted(leg.node_widgets[0])
        mock_exec.assert_not_called()
    assert len(leg.node_widgets) == 1
    assert leg.leg_data.nodes[0].test_name == "保留"
    assert not (root / "3.测试组").exists()


@patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes)
def test_delete_hooked_card_confirmed_removes_dir(mock_exec, tmp_path):
    _app()
    root = tmp_path / "proj"
    (_test_dir(root, "Leg 1", "湿热循环") / "试验前").mkdir(parents=True)
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="湿热循环")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    leg.on_node_deleted(leg.node_widgets[0])
    mock_exec.assert_called_once()
    assert leg.node_widgets == []
    assert leg.leg_data.nodes == []
    assert not _test_dir(root, "Leg 1", "湿热循环").exists()


@patch.object(QMessageBox, "exec", return_value=QMessageBox.No)
def test_delete_hooked_card_cancelled_keeps_card_and_dir(mock_exec, tmp_path):
    _app()
    root = tmp_path / "proj"
    (_test_dir(root, "Leg 1", "湿热循环") / "试验前").mkdir(parents=True)
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="湿热循环")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    leg.on_node_deleted(leg.node_widgets[0])
    mock_exec.assert_called_once()
    assert len(leg.node_widgets) == 1
    assert leg.leg_data.nodes[0].test_name == "湿热循环"
    assert (_test_dir(root, "Leg 1", "湿热循环") / "试验前").is_dir()


@patch.object(QMessageBox, "exec", return_value=QMessageBox.Yes)
def test_delete_leg_with_hooked_nodes_removes_dirs(mock_exec, tmp_path):
    _app()
    root = tmp_path / "proj"
    (_test_dir(root, "Leg 1", "A") / "试验前").mkdir(parents=True)
    (_test_dir(root, "Leg 1", "B") / "数据表附件").mkdir(parents=True)
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="A"), TestNode(test_name="B")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    area.on_leg_deleted(leg)
    mock_exec.assert_called_once()
    assert area.leg_widgets == []
    assert state.legs == []
    assert not _test_dir(root, "Leg 1", "A").exists()
    assert not _test_dir(root, "Leg 1", "B").exists()


def test_delete_unhooked_leg_without_confirm(tmp_path):
    _app()
    root = tmp_path / "proj"
    root.mkdir()
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="未挂钩")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    with patch.object(QMessageBox, "exec") as mock_exec:
        area.on_leg_deleted(leg)
        mock_exec.assert_not_called()
    assert area.leg_widgets == []
    assert state.legs == []


@patch.object(QMessageBox, "exec", return_value=QMessageBox.No)
def test_delete_leg_cancelled_keeps_structure(mock_exec, tmp_path):
    _app()
    root = tmp_path / "proj"
    (_test_dir(root, "Leg 1", "湿热循环") / "试验前").mkdir(parents=True)
    state = ProjectState(
        project_id="P1",
        project_path=str(root),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="湿热循环")],
            )
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg = area.leg_widgets[0]
    area.on_leg_deleted(leg)
    mock_exec.assert_called_once()
    assert len(area.leg_widgets) == 1
    assert len(state.legs) == 1
    assert (_test_dir(root, "Leg 1", "湿热循环") / "试验前").is_dir()


def test_complete_mark_reserves_width_without_changing_leg_width():
    _app()
    complete = TestNode(test_name="M-05Mechanical Shock")
    complete.apply_standards([TestStandard(standard_id="S1", chapter="1", test_name="M-05")])
    complete.equipments = [TestEquipment(name="设备", code="EQ-1")]
    complete.samples = [TestSample(sample_id="A01", result=TestResult.PASS)]
    incomplete = TestNode(test_name="M-04Vibration test")
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[complete]),
            TestLeg(leg_id="L2", leg_name="Leg 2", nodes=[incomplete]),
        ],
    )
    area = LegGraphArea(state)
    area.reload_from_state()
    leg1, leg2 = area.leg_widgets
    mark1 = leg1.node_widgets[0].lbl_complete
    mark2 = leg2.node_widgets[0].lbl_complete
    assert mark1.text() == "✓"
    assert mark2.text() == ""
    assert leg1.width() == leg2.width() == LEG_CARD_WIDTH


def test_fill_test_combo_anchors_long_name_at_start():
    _app()
    combo = QComboBox()
    combo.setEditable(True)
    fill_test_combo(combo, [], "M-05Mechanical Shock")
    assert combo.lineEdit().cursorPosition() == 0


def test_test_combo_tooltip_shows_full_name():
    _app()
    combo = QComboBox()
    combo.setEditable(True)
    fill_test_combo(combo, [], "M-05Mechanical Shock")
    assert combo.toolTip() == "M-05Mechanical Shock"
    assert combo.lineEdit().toolTip() == "M-05Mechanical Shock"
    fill_test_combo(combo, [], "")
    assert combo.toolTip() == ""
    assert combo.lineEdit().toolTip() == ""


def test_english_edit_does_not_rename_hooked_dir(tmp_path):
    _app()
    state = ProjectState(
        project_id="P1",
        project_path=str(tmp_path),
        edit_language="英文",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="高温试验", test_name_en="High temp")],
            )
        ],
    )
    hooked = _test_dir(tmp_path, "Leg 1", "高温试验")
    hooked.mkdir(parents=True)
    area = LegGraphArea(state)
    area.reload_from_state()
    nw = area.leg_widgets[0].node_widgets[0]
    nw._commit_english_name("Heat test")
    assert nw.node_data.test_name_en == "Heat test"
    assert nw.node_data.test_name == "高温试验"
    assert hooked.is_dir()
    assert not _test_dir(tmp_path, "Leg 1", "Heat test").exists()


def test_english_edit_pool_pick_updates_chinese_name_and_dir(tmp_path):
    _app()
    state = ProjectState(
        project_id="P1",
        project_path=str(tmp_path),
        edit_language="英文",
        candidate_pool=["振动试验"],
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="高温试验", test_name_en="High temp")],
            )
        ],
    )
    old_dir = _test_dir(tmp_path, "Leg 1", "高温试验")
    old_dir.mkdir(parents=True)
    area = LegGraphArea(state)
    area.reload_from_state()
    nw = area.leg_widgets[0].node_widgets[0]
    nw.combo.setEditText("振动试验")
    nw.on_test_edit_finished()
    assert nw.node_data.test_name == "振动试验"
    assert not old_dir.exists()
    assert _test_dir(tmp_path, "Leg 1", "振动试验").is_dir()


if __name__ == "__main__":
    test_reloaded_nodes_get_db_loader()
    test_added_nodes_get_db_loader()
    test_combo_keeps_typed_name_without_custom_option()
    test_gantt_follows_state_reassignment()
    test_gantt_marks_overlapping_nodes()
    test_gantt_leg_bar_is_move_only()
    test_gantt_scheduled_row_miss_does_not_create()
    test_gantt_axis_extends_past_last_bar()
    print("test_leg_graph: ok")
