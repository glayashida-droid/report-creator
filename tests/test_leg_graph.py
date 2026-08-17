import sys

from PySide6.QtWidgets import QApplication

from src.models.project_state import ProjectState, TestLeg, TestNode
from src.ui.leg_graph import LegGraphArea


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


if __name__ == "__main__":
    test_reloaded_nodes_get_db_loader()
    test_added_nodes_get_db_loader()
    print("test_leg_graph: ok")
