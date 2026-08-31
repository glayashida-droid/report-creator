from pathlib import Path
from src.models.project_state import ProjectState, TestLeg, TestNode, TestSample, TestResult, TestStandard

_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_project_state():
    state = ProjectState(
        project_id="A2260613686101",
        applicant_name="Test Company",
        sample_name="Test Sample"
    )
    
    node = TestNode(
        test_name="盐雾试验",
        standard_id="VW 80000",
        samples=[TestSample(sample_id="A01", result=TestResult.PASS)]
    )
    
    leg = TestLeg(leg_id="L1", leg_name="Leg 1")
    leg.nodes.append(node)
    
    state.legs.append(leg)
    
    test_path = Path(".scratch/test_state.json")
    state.save_to_file(str(test_path))
    
    print("Saved state to:", test_path)
    
    loaded_state = ProjectState.load_from_file(str(test_path))
    print("Loaded project_id:", loaded_state.project_id)
    print("Loaded test name:", loaded_state.legs[0].nodes[0].test_name)
    
    if test_path.exists():
        test_path.unlink()


def test_project_saves_standard_images_and_edits():
    state = ProjectState(project_id="P1")
    node = TestNode(test_name="试验A2")
    node.apply_standards(
        [
            TestStandard(
                standard_id="ABC",
                chapter="1.1",
                test_name="试验A",
                standard_desc="我改过的条件",
                result_desc="我改过的结果",
                evaluation_req="我改过的要求",
                key_params=["（90±2.5）℃"],
                key_params_defaults=["（70±2.5）℃"],
                key_params_confirmed=True,
                images=[_MIN_PNG],
            )
        ]
    )
    state.legs.append(TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[node]))
    path = Path(".scratch/test_state_images.json")
    state.save_to_file(str(path))
    try:
        loaded = ProjectState.load_from_file(str(path))
        std = loaded.legs[0].nodes[0].standards[0]
        assert loaded.legs[0].nodes[0].test_name == "试验A2"
        assert std.standard_desc == "我改过的条件"
        assert std.result_desc == "我改过的结果"
        assert std.evaluation_req == "我改过的要求"
        assert std.key_params == ["（90±2.5）℃"]
        assert std.key_params_defaults == ["（70±2.5）℃"]
        assert std.key_params_confirmed is True
        assert std.images == [_MIN_PNG]
    finally:
        if path.exists():
            path.unlink()


def test_duplicate_test_names_within_same_leg():
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="湿热循环"),
                    TestNode(test_name="湿热循环"),
                    TestNode(test_name=""),
                ],
            ),
            TestLeg(
                leg_id="L2",
                leg_name="Leg 2",
                nodes=[TestNode(test_name="振动"), TestNode(test_name="湿热循环")],
            ),
        ],
    )
    assert state.duplicate_test_names() == ["湿热循环"]
    assert not state.test_name_is_unique_in_leg("L1", "湿热循环")
    assert state.test_name_is_unique_in_leg("L2", "湿热循环")
    assert state.test_name_is_unique_in_leg("L1", "振动")
    assert state.test_name_usage_count_in_leg("L1", "湿热循环") == 2
    assert state.test_name_usage_count_in_leg("L2", "湿热循环") == 1
    assert state.test_name_usage_count("湿热循环") == 3


def test_cross_leg_same_name_is_not_duplicate():
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="温湿度试验")],
            ),
            TestLeg(
                leg_id="L2",
                leg_name="Leg 2",
                nodes=[TestNode(test_name="温湿度试验")],
            ),
        ],
    )
    assert state.duplicate_test_names() == []
    assert state.test_name_is_unique_in_leg("L1", "温湿度试验")
    assert state.test_name_is_unique_in_leg("L2", "温湿度试验")


def test_duplicate_test_names_ignores_placeholder_and_custom():
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="请选择试验..."),
                    TestNode(test_name="请选择试验..."),
                    TestNode(test_name="自定义"),
                ],
            )
        ],
    )
    assert state.duplicate_test_names() == []


def test_save_state_blocks_duplicate_test_names_in_same_leg(tmp_path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    win = MainWindow()
    win.state.project_id = "P1"
    win.state.legs = [
        TestLeg(
            leg_id="L1",
            leg_name="Leg 1",
            nodes=[
                TestNode(test_name="湿热循环"),
                TestNode(test_name="湿热循环"),
            ],
        )
    ]
    win._local_path = tmp_path
    with patch("src.ui.main_window.warn_duplicate_test_names") as warn:
        assert win.save_state(show_success=False) is False
        warn.assert_called_once()
    assert not (tmp_path / "project_state.json").exists()


if __name__ == "__main__":
    test_project_state()
    test_project_saves_standard_images_and_edits()
    test_duplicate_test_names_within_same_leg()
    test_cross_leg_same_name_is_not_duplicate()
    test_duplicate_test_names_ignores_placeholder_and_custom()
    print("test_project_state: ok")
