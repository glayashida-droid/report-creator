"""Card test names: sync from standards and unified report labels."""

from src.generators.word_engine import WordGenerator
from src.language_copy import language_text
from src.models.project_state import (
    ProjectState,
    TestLeg,
    TestNode,
    TestStandard,
)


def test_sync_card_names_uses_first_standard_only():
    node = TestNode(test_name="报价随机振动试验")
    node.apply_standards(
        [
            TestStandard(
                standard_id="A",
                chapter="1",
                test_name="随机振动",
                test_item="Random vibration",
            ),
            TestStandard(
                standard_id="B",
                chapter="2",
                test_name="第二项",
                test_item="Second item",
            ),
        ]
    )
    node.sync_card_names_from_standards()
    assert node.test_name == "随机振动"
    assert node.test_name_en == "Random vibration"


def test_sync_clears_english_when_test_item_missing():
    node = TestNode(test_name="报价名", test_name_en="Old EN")
    node.apply_standards(
        [
            TestStandard(
                standard_id="A",
                chapter="1",
                test_name="高温",
                test_item="",
            )
        ]
    )
    node.sync_card_names_from_standards()
    assert node.test_name == "高温"
    assert node.test_name_en == ""


def test_report_label_uses_card_names_not_joined_test_item():
    node = TestNode(
        test_name="卡片中文",
        test_name_en="Card EN",
        standards=[
            TestStandard(
                standard_id="A",
                chapter="1",
                test_name="库内名",
                test_item="Library EN",
            )
        ],
    )
    assert language_text(node.test_name, node.test_name_en, "中文") == "卡片中文"
    assert language_text(node.test_name, node.test_name_en, "英文") == "Card EN"
    assert language_text(node.test_name, node.test_name_en, "中英文") == "卡片中文 / Card EN"


def test_load_backfills_test_name_en_from_standards(tmp_path):
    node = TestNode(test_name="高温试验")
    node.apply_standards(
        [
            TestStandard(
                standard_id="A",
                chapter="1",
                test_name="高温",
                test_item="High temperature",
            )
        ]
    )
    state = ProjectState(project_id="P1", legs=[TestLeg(leg_id="L1", leg_name="L1", nodes=[node])])
    path = tmp_path / "s.json"
    state.save_to_file(str(path))
    loaded = ProjectState.load_from_file(str(path))
    assert loaded.legs[0].nodes[0].test_name_en == "High temperature"


def test_word_export_english_uses_card_name_en(tmp_path):
    from pathlib import Path

    from docx import Document

    from src.models.project_state import TestEquipment, TestSample, TestResult

    node = TestNode(
        test_name="高温",
        test_name_en="High temperature",
        standards=[
            TestStandard(
                standard_id="VW",
                chapter="4.1",
                test_name="高温",
                test_item="Library fallback",
                standard_desc="条件",
                standard_desc_en="Condition",
                evaluation_req="评判",
                evaluation_req_en="Eval",
                result_desc="结果",
                result_desc_en="Result",
            )
        ],
        equipments=[TestEquipment(name="箱", code="C1")],
        samples=[TestSample(sample_id="A01", result=TestResult.PASS)],
    )
    node.apply_standards(node.standards)
    state = ProjectState(
        project_id="A2260999000101",
        applicant_name="委托方",
        applicant_name_en="Customer",
        sample_name="样品",
        sample_name_en="Sample",
        application_fields={"申请单号": "A1", "申请公司": "委托方", "样品名称": "样品"},
        application_fields_en={"申请公司": "Customer", "样品名称": "Sample"},
    )
    state.legs.append(TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[node]))
    template = Path("templates/template_en.docx")
    out = Path(tmp_path) / "en.docx"
    WordGenerator(str(template)).generate(
        state, str(out), report_language="英文"
    )
    doc = Document(str(out))
    blob = "\n".join(p.text for p in doc.paragraphs)
    assert "High temperature" in blob
    assert "Library fallback" not in blob


if __name__ == "__main__":
    test_sync_card_names_uses_first_standard_only()
    test_sync_clears_english_when_test_item_missing()
    test_report_label_uses_card_names_not_joined_test_item()
    print("test_card_names: ok (run pytest for tmp_path tests)")
