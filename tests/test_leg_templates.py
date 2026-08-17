import json
import os
import tempfile
from pathlib import Path

from src.io.leg_templates import (
    TemplateExistsError,
    TemplateNameError,
    apply_leg_template,
    list_leg_templates,
    load_leg_template,
    save_leg_template,
    unique_test_names,
)
from src.models.project_state import (
    ProjectState,
    TestEquipment,
    TestLeg,
    TestNode,
    TestResult,
    TestSample,
    TestStandard,
)


def _sample_legs():
    return [
        TestLeg(
            leg_id="L1",
            leg_name="Leg 1",
            nodes=[
                TestNode(
                    test_name="随机振动",
                    standard_id="VW 80000",
                    standard_chapter="4.1",
                    standard_test_name="随机振动",
                    standard_desc="随机振动条件",
                    result_desc="功能正常",
                    evaluation_req="无损坏",
                    standards=[
                        TestStandard(
                            standard_id="VW 80000",
                            chapter="4.1",
                            test_name="随机振动",
                            standard_desc="随机振动条件",
                            result_desc="功能正常",
                            evaluation_req="无损坏",
                        )
                    ],
                    equipment_name="振动台",
                    equipments=[TestEquipment(name="振动台", code="EQ-1")],
                    start_date="2026-08-01",
                    end_date="2026-08-02",
                    samples=[TestSample(sample_id="A01", result=TestResult.PASS)],
                ),
                TestNode(test_name="绝缘电阻"),
            ],
        ),
        TestLeg(
            leg_id="L2",
            leg_name="Leg 2",
            nodes=[TestNode(test_name="随机振动")],
        ),
    ]


def test_combo_pool_exact_dedupe_keeps_similar_names():
    state = ProjectState(
        candidate_pool=["随机振动试验", "绝缘电阻"],
        template_pool=["随机振动", "绝缘电阻", "短暂过压"],
    )
    assert state.combo_pool() == ["随机振动试验", "绝缘电阻", "随机振动", "短暂过压"]
    assert state.combo_pool(extra="绝缘电阻") == ["随机振动试验", "绝缘电阻", "随机振动", "短暂过压"]
    assert state.combo_pool(extra="目视检查")[-1] == "目视检查"


def test_save_strips_project_fields_and_keeps_standards():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        path = save_leg_template("宇通-电性能", _sample_legs(), templates_dir=dest)
        data = json.loads(path.read_text(encoding="utf-8"))
        node = data["legs"][0]["nodes"][0]
        assert data["name"] == "宇通-电性能"
        assert node["test_name"] == "随机振动"
        assert node["standard_id"] == "VW 80000"
        assert node["standard_chapter"] == "4.1"
        assert not node.get("standard_desc")
        assert not node.get("result_desc")
        assert not node.get("evaluation_req")
        assert node["standards"][0]["standard_id"] == "VW 80000"
        assert node["standards"][0]["chapter"] == "4.1"
        assert not node["standards"][0].get("standard_desc")
        assert not node["standards"][0].get("result_desc")
        assert not node["standards"][0].get("evaluation_req")
        assert not node["standards"][0].get("images")
        assert not node["standards"][0].get("key_params")
        assert not node["standards"][0].get("key_params_defaults")
        assert not node["standards"][0].get("key_params_confirmed")
        assert not node.get("equipment_name")
        assert node.get("equipments") == []
        assert not node.get("start_date")
        assert not node.get("end_date")
        assert node.get("samples") == []


def test_save_rejects_blank_and_duplicate_without_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        try:
            save_leg_template("  ", _sample_legs(), templates_dir=dest)
            assert False, "expected TemplateNameError"
        except TemplateNameError:
            pass
        save_leg_template("常规", _sample_legs(), templates_dir=dest)
        try:
            save_leg_template("常规", _sample_legs(), templates_dir=dest)
            assert False, "expected TemplateExistsError"
        except TemplateExistsError as exc:
            assert exc.name == "常规"
        path = save_leg_template("常规", _sample_legs(), templates_dir=dest, overwrite=True)
        assert path.exists()


def test_import_does_not_mutate_quotation_pool_or_rewrite_names():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        save_leg_template("宇通-电性能", _sample_legs(), templates_dir=dest)
        name, legs = load_leg_template(dest / "宇通-电性能.json")
        state = ProjectState(
            project_id="A2260542168101",
            candidate_pool=["随机振动试验", "绝缘电阻试验"],
            applicant_name="宇通",
        )
        apply_leg_template(state, name, legs)
        assert state.candidate_pool == ["随机振动试验", "绝缘电阻试验"]
        assert state.template_pool == ["随机振动", "绝缘电阻"]
        assert unique_test_names(state.legs) == ["随机振动", "绝缘电阻"]
        assert state.legs[0].nodes[0].test_name == "随机振动"
        assert state.legs[0].nodes[0].standard_id == "VW 80000"
        assert not state.legs[0].nodes[0].standard_desc
        assert not state.legs[0].nodes[0].standards[0].result_desc
        assert not state.legs[0].nodes[0].standards[0].images
        assert not state.legs[0].nodes[0].equipment_name
        assert state.legs[0].nodes[0].samples == []
        assert state.last_leg_template_name == "宇通-电性能"
        assert state.combo_pool() == [
            "随机振动试验",
            "绝缘电阻试验",
            "随机振动",
            "绝缘电阻",
        ]


def test_list_templates_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        old_path = save_leg_template("旧模板", _sample_legs(), templates_dir=dest)
        new_path = save_leg_template("新模板", _sample_legs(), templates_dir=dest)
        newer = old_path.stat().st_mtime + 5
        os.utime(new_path, (newer, newer))
        listed = list_leg_templates(dest)
        assert [item.name for item in listed] == ["新模板", "旧模板"]
        assert listed[0].leg_count == 2
        assert listed[0].test_count == 3


def test_import_hydrates_content_from_catalog_not_template_file():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        save_leg_template("宇通-电性能", _sample_legs(), templates_dir=dest)
        name, legs = load_leg_template(dest / "宇通-电性能.json")
        catalog = [
            {
                "标准号": "VW 80000",
                "章节号": "4.1",
                "试验名称": "库内名称",
                "标准描述": "最新条件",
                "结果描述": "最新结果",
                "评价要求": "最新要求",
                "关键参数": "（70±2.5）℃",
                "_images": [b"\x89PNG"],
            }
        ]
        state = ProjectState(project_id="A1", candidate_pool=["报价名"])
        apply_leg_template(state, name, legs, catalog=catalog)
        node = state.legs[0].nodes[0]
        assert node.test_name == "随机振动"
        assert node.standards[0].test_name == "库内名称"
        assert node.standards[0].standard_desc == "最新条件"
        assert node.standards[0].result_desc == "最新结果"
        assert node.standards[0].evaluation_req == "最新要求"
        assert node.standards[0].images == [b"\x89PNG"]
        assert node.standards[0].key_params_defaults == ["（70±2.5）℃"]
        assert node.standards[0].key_params == ["（70±2.5）℃"]
        assert node.standards[0].key_params_confirmed is False
        assert node.standard_desc == "最新条件"


def test_load_legacy_template_file_drops_stale_content():
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "旧.json"
        path.write_text(
            json.dumps(
                {
                    "name": "旧",
                    "legs": [
                        {
                            "leg_id": "L1",
                            "leg_name": "Leg 1",
                            "nodes": [
                                {
                                    "test_name": "试验A2",
                                    "standard_id": "ABC",
                                    "standard_chapter": "1.1",
                                    "standard_desc": "过期条件",
                                    "result_desc": "过期结果",
                                    "evaluation_req": "过期要求",
                                    "standards": [
                                        {
                                            "standard_id": "ABC",
                                            "chapter": "1.1",
                                            "test_name": "试验A",
                                            "standard_desc": "过期条件",
                                            "result_desc": "过期结果",
                                            "evaluation_req": "过期要求",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        name, legs = load_leg_template(path)
        assert name == "旧"
        node = legs[0].nodes[0]
        assert node.test_name == "试验A2"
        assert node.standards[0].standard_id == "ABC"
        assert node.standards[0].chapter == "1.1"
        assert not node.standard_desc
        assert not node.standards[0].result_desc


if __name__ == "__main__":
    test_combo_pool_exact_dedupe_keeps_similar_names()
    test_save_strips_project_fields_and_keeps_standards()
    test_save_rejects_blank_and_duplicate_without_overwrite()
    test_import_does_not_mutate_quotation_pool_or_rewrite_names()
    test_list_templates_newest_first()
    test_import_hydrates_content_from_catalog_not_template_file()
    test_load_legacy_template_file_drops_stale_content()
    print("test_leg_templates: ok")
