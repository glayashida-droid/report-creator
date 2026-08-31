"""TKT-3: bilingual standard/equipment fields on state (no GUI layout)."""

from src.models.project_state import (
    TestEquipment,
    TestNode,
    TestResult,
    TestStandard,
)
from src.parsers.db_loader import hydrate_standard_from_record
from src.parsers.key_params import apply_key_params


def test_hydrate_loads_english_columns():
    std = TestStandard(standard_id="VW", chapter="4.1")
    rec = {
        "标准号": "VW",
        "章节号": "4.1",
        "试验名称": "高温",
        "test item": "High temperature",
        "标准描述": "在（70±2.5）℃下保持",
        "condition": "Keep at (70±2.5)℃",
        "评价要求": "无损坏",
        "Evaluation requirement": "No damage",
        "结果描述": "完好",
        "result": "Intact",
        "关键参数": "（70±2.5）℃",
    }
    out = hydrate_standard_from_record(std, rec)
    assert out.standard_desc == "在（70±2.5）℃下保持"
    assert out.standard_desc_en == "Keep at (70±2.5)℃"
    assert out.evaluation_req_en == "No damage"
    assert out.result_desc_en == "Intact"
    assert out.test_item == "High temperature"


def test_key_params_replace_both_condition_sides():
    defaults = ["（70±2.5）℃"]
    values = ["（90±2.5）℃"]
    cn = apply_key_params("在（70±2.5）℃下保持", defaults, values)
    en = apply_key_params("Keep at （70±2.5）℃", defaults, values)
    assert cn == "在（90±2.5）℃下保持"
    assert en == "Keep at （90±2.5）℃"


def test_apply_standards_persists_en_and_test_item(tmp_path):
    from pathlib import Path
    from src.models.project_state import ProjectState, TestLeg

    node = TestNode(test_name="高温试验")
    node.apply_standards(
        [
            TestStandard(
                standard_id="A",
                chapter="1",
                test_name="高温",
                test_item="High temperature",
                standard_desc="中文条件",
                standard_desc_en="EN condition",
                evaluation_req="中文评判",
                evaluation_req_en="EN eval",
                result_desc="中文结果",
                result_desc_en="EN result",
            )
        ]
    )
    node.sync_card_names_from_standards()
    assert node.test_name == "高温"
    assert node.test_name_en == "High temperature"
    assert node.standard_desc == "中文条件"
    assert node.standard_desc_en == "EN condition"
    assert node.evaluation_req_en == "EN eval"
    assert node.result_desc_en == "EN result"
    assert node.joined_test_item() == "High temperature"

    node.equipments = [
        TestEquipment(name="高低温箱", name_en="Temp chamber", code="T1")
    ]
    state = ProjectState(project_id="P1", edit_language="英文")
    state.legs.append(TestLeg(leg_id="L1", leg_name="L1", nodes=[node]))
    path = Path(tmp_path) / "s.json"
    state.save_to_file(str(path))
    loaded = ProjectState.load_from_file(str(path))
    std = loaded.legs[0].nodes[0].standards[0]
    assert std.standard_desc_en == "EN condition"
    assert std.test_item == "High temperature"
    assert loaded.legs[0].nodes[0].equipments[0].name_en == "Temp chamber"
    assert loaded.edit_language == "英文"


def test_detail_complete_without_english():
    node = TestNode(
        test_name="高温",
        standards=[
            TestStandard(
                standard_id="A",
                chapter="1",
                test_name="高温",
                standard_desc="条件",
                key_params_defaults=["1"],
                key_params=["1"],
                key_params_confirmed=True,
            )
        ],
        equipments=[TestEquipment(name="箱", code="C1")],
        samples=[{"sample_id": "A01", "result": TestResult.PASS}],
    )
    assert node.is_detail_complete()
