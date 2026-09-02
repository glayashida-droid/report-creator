from src.models.project_state import TestNode, TestStandard


def _std(sid, chapter, name, desc, result, eval_req):
    return TestStandard(
        standard_id=sid,
        chapter=chapter,
        test_name=name,
        standard_desc=desc,
        result_desc=result,
        evaluation_req=eval_req,
    )


def test_join_follows_selection_order_not_library_order():
    first = _std("GB/T 1", "8.1", "冲击", "条件甲", "描述甲", "要求甲")
    second = _std("VW 2", "4.2", "振动", "条件乙", "描述乙", "要求乙")
    node = TestNode(test_name="机械冲击")
    node.apply_standards([second, first])

    assert [s.standard_id for s in node.standards] == ["VW 2", "GB/T 1"]
    assert node.joined_test_method() == "VW 2 / 4.2；GB/T 1 / 8.1"
    assert node.joined_standard_desc() == "条件乙\n\n条件甲"
    assert node.joined_evaluation_req() == "要求乙\n\n要求甲"
    assert node.result_desc is None
    assert [s.result_desc for s in node.resolved_standards()] == ["描述乙", "描述甲"]


def test_single_standard_keeps_result_desc_scalar():
    node = TestNode(test_name="绝缘电阻")
    node.apply_standards([_std("ISO 1", "5", "绝缘", "条件", "功能正常", "无损坏")])
    assert node.result_desc == "功能正常"
    assert node.standard_desc == "条件"
    assert node.evaluation_req == "无损坏"


def test_legacy_scalar_fields_still_resolve():
    node = TestNode(
        test_name="盐雾",
        standard_id="VW 80000",
        standard_chapter="4.1",
        standard_test_name="盐雾",
        standard_desc="喷盐",
        result_desc="无腐蚀",
        evaluation_req="表面完好",
    )
    stds = node.resolved_standards()
    assert len(stds) == 1
    assert stds[0].standard_id == "VW 80000"
    assert node.joined_standard_desc() == "喷盐"
    assert stds[0].result_desc == "无腐蚀"


def test_resolved_test_method_prefers_edited_text():
    node = TestNode(test_name="盐雾", test_method="VW82511-2010 / 8.3.6 盐雾")
    node.apply_standards([
        _std("VW82511-2010", "8.3.6", "盐雾试验", "条件", "描述", "要求"),
    ])
    assert node.joined_test_method() == "VW82511-2010 / 8.3.6"
    assert node.resolved_test_method() == "VW82511-2010 / 8.3.6 盐雾"

    node2 = TestNode(test_name="盐雾")
    node2.apply_standards([
        _std("VW82511-2010", "8.3.6", "盐雾试验", "条件", "描述", "要求"),
    ])
    assert node2.resolved_test_method() == "VW82511-2010 / 8.3.6"


def test_resolved_env_condition_prefers_node_then_standard():
    node = TestNode(test_name="振动", env_condition="（23±5）℃，（50±25）%RH")
    node.apply_standards([
        _std("VW 2", "4.2", "振动", "条件", "描述", "要求"),
    ])
    assert node.resolved_env_condition() == "（23±5）℃，（50±25）%RH"

    node2 = TestNode(test_name="振动")
    node2.apply_standards([
        TestStandard(
            standard_id="VW 2",
            chapter="4.2",
            test_name="振动",
            env_condition="(25±5)°C (50±25)%Rh",
        )
    ])
    assert node2.resolved_env_condition() == "(25±5)°C (50±25)%Rh"


if __name__ == "__main__":
    test_join_follows_selection_order_not_library_order()
    test_single_standard_keeps_result_desc_scalar()
    test_legacy_scalar_fields_still_resolve()
    test_resolved_test_method_prefers_edited_text()
    print("test_standards_mapping: ok")
