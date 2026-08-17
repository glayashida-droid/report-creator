import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit

from src.models.project_state import (
    ProjectState,
    TestEquipment,
    TestLeg,
    TestNode,
    TestSample,
    TestResult,
    TestStandard,
)
from src.parsers.db_loader import hydrate_standard_from_record
from src.parsers.key_params import KeyParamReplaceError, apply_key_params, parse_key_params
from src.ui.test_detail_dialog import TestDetailDialog


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_parse_splits_ascii_and_chinese_commas():
    assert parse_key_params("") == []
    assert parse_key_params(None) == []
    assert parse_key_params("（70±2.5）℃") == ["（70±2.5）℃"]
    assert parse_key_params("（70±2.5）℃,24 h") == ["（70±2.5）℃", "24 h"]
    assert parse_key_params("（70±2.5）℃，24 h，100mA") == ["（70±2.5）℃", "24 h", "100mA"]


def test_apply_replaces_from_original_not_previous_result():
    original = "将样品在（70±2.5）℃恒温箱中保持408小时。"
    defaults = ["（70±2.5）℃"]
    first = apply_key_params(original, defaults, ["（85±2.5）℃"])
    assert first == "将样品在（85±2.5）℃恒温箱中保持408小时。"
    second = apply_key_params(original, defaults, ["（90±2.5）℃"])
    assert second == "将样品在（90±2.5）℃恒温箱中保持408小时。"
    assert "70" not in second
    assert "85" not in second


def test_apply_replaces_multiple_and_longest_first():
    original = "温度（70±2.5）℃，电流100mA，时长24 h。"
    defaults = ["（70±2.5）℃", "100mA", "24 h"]
    out = apply_key_params(original, defaults, ["（90±2.5）℃", "80mA", "48 h"])
    assert out == "温度（90±2.5）℃，电流80mA，时长48 h。"


def test_apply_raises_when_token_missing():
    try:
        apply_key_params("没有这个温度", ["（70±2.5）℃"], ["（90±2.5）℃"])
        assert False, "expected KeyParamReplaceError"
    except KeyParamReplaceError as exc:
        assert "（70±2.5）℃" in str(exc)
        assert exc.missing == ["（70±2.5）℃"]


def test_hydrate_copies_key_params_unconfirmed():
    std = TestStandard(standard_id="ABC", chapter="1.1")
    rec = {
        "标准号": "ABC",
        "章节号": "1.1",
        "试验名称": "耐热",
        "标准描述": "在（70±2.5）℃下保持",
        "结果描述": "完好",
        "评价要求": "无损坏",
        "关键参数": "（70±2.5）℃",
    }
    out = hydrate_standard_from_record(std, rec)
    assert out.key_params_defaults == ["（70±2.5）℃"]
    assert out.key_params == ["（70±2.5）℃"]
    assert out.key_params_confirmed is False
    assert out.needs_key_param_confirm() is True


def _filled_node(**std_kwargs):
    node = TestNode(test_name="耐热")
    node.apply_standards(
        [
            TestStandard(
                standard_id="ABC",
                chapter="1.1",
                test_name="耐热",
                standard_desc="在（70±2.5）℃下保持",
                **std_kwargs,
            )
        ]
    )
    node.equipments = [TestEquipment(name="恒温箱", code="EQ-1")]
    node.samples = [TestSample(sample_id="A01", result=TestResult.PASS)]
    return node


def test_detail_complete_requires_key_param_confirm():
    pending = _filled_node(key_params_defaults=["（70±2.5）℃"], key_params_confirmed=False)
    assert pending.is_detail_complete() is False
    done = _filled_node(key_params_defaults=["（70±2.5）℃"], key_params_confirmed=True)
    assert done.is_detail_complete() is True
    no_params = _filled_node()
    assert no_params.is_detail_complete() is True


def test_incomplete_export_labels_follow_scope():
    pending = _filled_node(key_params_defaults=["（70±2.5）℃"], key_params_confirmed=False)
    done = _filled_node(key_params_defaults=["（70±2.5）℃"], key_params_confirmed=True)
    done.test_name = "冲击"
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[pending]),
            TestLeg(leg_id="L2", leg_name="Leg 2", nodes=[done]),
        ],
    )
    assert state.incomplete_export_labels() == ["Leg 1 / 耐热"]
    assert state.incomplete_export_labels("L2") == []
    assert state.incomplete_export_labels("TEST:Leg 1 - 耐热") == ["Leg 1 / 耐热"]
    assert state.incomplete_export_labels("TEST:Leg 2 - 冲击") == []


def test_dialog_confirm_uncheck_reconfirm_uses_original():
    _app()
    original = "将样品在（70±2.5）℃恒温箱中保持408小时。"
    node = TestNode(test_name="耐热")
    catalog = [
        {
            "标准号": "ABC",
            "章节号": "1.1",
            "试验名称": "耐热",
            "标准描述": original,
            "评价要求": "无损坏",
            "结果描述": "完好",
            "关键参数": "（70±2.5）℃",
        }
    ]
    dlg = TestDetailDialog(node, catalog, [])
    try:
        dlg.show()
        dlg.std_table.item(0, 0).setCheckState(Qt.Checked)
        drawer = dlg._cond_drawers[0]
        assert not drawer.accessory.isHidden()
        param_edits = drawer.accessory.findChildren(QLineEdit, "keyParamEdit")
        assert len(param_edits) == 1
        assert param_edits[0].text() == "（70±2.5）℃"
        editor = dlg._cond_editors[("ABC", "1.1")]
        assert editor.toPlainText() == original

        param_edits[0].setText("（85±2.5）℃")
        chk = drawer.accessory.findChild(QCheckBox, "keyParamCheck")
        chk.setChecked(True)
        assert "（85±2.5）℃" in editor.toPlainText()
        assert "70" not in editor.toPlainText()
        assert dlg._key_param_confirmed[("ABC", "1.1")] is True

        chk.setChecked(False)
        assert editor.toPlainText() == original
        assert param_edits[0].text() == "（85±2.5）℃"

        param_edits[0].setText("（90±2.5）℃")
        chk.setChecked(True)
        assert editor.toPlainText() == "将样品在（90±2.5）℃恒温箱中保持408小时。"
        assert "70" not in editor.toPlainText()
        assert "85" not in editor.toPlainText()

        picked = dlg._selected_standards()
        assert picked[0].key_params == ["（90±2.5）℃"]
        assert picked[0].key_params_confirmed is True
        assert picked[0].standard_desc == editor.toPlainText()
    finally:
        dlg.close()


if __name__ == "__main__":
    test_parse_splits_ascii_and_chinese_commas()
    test_apply_replaces_from_original_not_previous_result()
    test_apply_replaces_multiple_and_longest_first()
    test_apply_raises_when_token_missing()
    test_hydrate_copies_key_params_unconfirmed()
    test_detail_complete_requires_key_param_confirm()
    test_incomplete_export_labels_follow_scope()
    test_dialog_confirm_uncheck_reconfirm_uses_original()
    print("test_key_params: ok")
