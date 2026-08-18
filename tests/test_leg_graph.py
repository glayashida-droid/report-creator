import sys

from PySide6.QtWidgets import QApplication, QComboBox

from src.models.project_state import ProjectState, TestLeg, TestNode
from src.ui.leg_graph import CUSTOM_TEST, PLACEHOLDER_TEST, LegGraphArea, fill_test_combo


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


if __name__ == "__main__":
    test_reloaded_nodes_get_db_loader()
    test_added_nodes_get_db_loader()
    test_combo_includes_custom_and_keeps_typed_name()
    print("test_leg_graph: ok")
