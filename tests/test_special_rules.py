"""Tests for OEM/customer special report rules."""

from pathlib import Path

import pytest

from src.io.special_rules import (
    SpecialRuleRow,
    load_special_rules,
    refresh_special_profile,
    resolve_special_profile,
    rule_keyword_matches,
    state_has_forbidden_na,
)
from src.models.project_state import (
    CustomOverviewField,
    ProjectState,
    SpecialReportProfile,
    TestLeg,
    TestNode,
    TestResult,
    TestSample,
)


def test_rule_keyword_contains_chinese():
    assert rule_keyword_matches("奥迪", "一汽奥迪")
    assert rule_keyword_matches("奥迪", "上汽奥迪汽车有限公司")
    assert rule_keyword_matches("吉利", "吉利汽车研究院")


def test_rule_keyword_english_alias():
    assert rule_keyword_matches("volvo", "Volvo Cars")
    assert rule_keyword_matches("haman", "Harman International")


def test_resolve_geely_profile_from_fixture(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "special.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["主机厂", "oem", "客户", "client", "汇总表试验周期", "测试员名字", "4签", "试验结论", "地址"])
    ws.append(
        [
            "吉利",
            "",
            "",
            "",
            "是",
            "",
            "是",
            "是",
            "上海市闵行区新骏环路777号5号楼/Building 5, No. 777, Xinjun Ring Road",
        ]
    )
    ws.append(
        [
            "",
            "",
            "哈曼",
            "haman",
            "",
            "",
            "是",
            "",
            "上海市闵行区万芳路1351号/Wanfang Road",
        ]
    )
    wb.save(path)

    state = ProjectState(
        application_fields={"主机厂": "吉利汽车", "申请公司": "哈曼汽车"},
    )
    profile = resolve_special_profile(state, rules=load_special_rules(path))
    assert profile.show_test_period is True
    assert profile.use_4sign is True
    assert profile.forbid_na is True
    assert "新骏环路" in profile.lab_address_cn


def test_address_oem_wins_over_client(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "special.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["主机厂", "oem", "客户", "client", "汇总表试验周期", "测试员名字", "4签", "试验结论", "地址"])
    ws.append(["吉利", "", "", "", "", "", "", "", "地址OEM/Address OEM"])
    ws.append(["", "", "哈曼", "haman", "", "", "", "", "地址Client/Address Client"])
    wb.save(path)

    state = ProjectState(
        application_fields={"主机厂": "吉利", "申请公司": "哈曼"},
    )
    profile = resolve_special_profile(state, rules=load_special_rules(path))
    assert profile.lab_address_cn == "地址OEM"


def _geely_rules():
    return [
        SpecialRuleRow(
            oem_cn="吉利",
            show_test_period=True,
            use_4sign=True,
            forbid_na=True,
        )
    ]


def test_custom_overview_exact_oem_label_triggers():
    state = ProjectState(
        custom_overview_fields=[
            CustomOverviewField(label_cn="主机厂", value_cn="吉利汽车"),
        ]
    )
    profile = resolve_special_profile(state, rules=_geely_rules())
    assert profile.show_test_period is True
    assert profile.use_4sign is True
    assert profile.forbid_na is True


def test_custom_overview_english_oem_label_triggers():
    state = ProjectState(
        custom_overview_fields=[
            CustomOverviewField(label_en="OEM", value_cn="吉利汽车"),
        ]
    )
    profile = resolve_special_profile(state, rules=_geely_rules())
    assert profile.show_test_period is True
    assert profile.use_4sign is True
    assert profile.forbid_na is True


def test_custom_overview_near_oem_label_does_not_trigger():
    state = ProjectState(
        custom_overview_fields=[
            CustomOverviewField(label_cn="主机厂名称", value_cn="吉利汽车"),
            CustomOverviewField(label_en="Original Equipment Manufacturer", value_en="Geely"),
        ]
    )
    profile = resolve_special_profile(state, rules=_geely_rules())
    assert profile.show_test_period is False
    assert profile.use_4sign is False
    assert profile.forbid_na is False


def test_custom_overview_oem_unions_with_parsed_field():
    state = ProjectState(
        application_fields={"主机厂": "蔚来"},
        custom_overview_fields=[
            CustomOverviewField(label_cn="主机厂", value_cn="吉利"),
        ],
    )
    rules = _geely_rules() + [
        SpecialRuleRow(oem_cn="蔚来", show_tester=True),
    ]
    profile = resolve_special_profile(state, rules=rules)
    assert profile.show_test_period is True
    assert profile.show_tester is True


def test_refresh_special_profile_on_state():
    state = ProjectState(application_fields={"主机厂": "蔚来"})
    rules = [
        SpecialRuleRow(
            oem_cn="蔚来",
            show_test_period=True,
            show_tester=True,
        )
    ]
    profile = resolve_special_profile(state, rules=rules)
    state.special_profile = profile
    assert profile.show_tester is True


def test_state_has_forbidden_na():
    node = TestNode(
        test_name="试验A",
        samples=[TestSample(sample_id="A01", result=TestResult.NA)],
    )
    leg = TestLeg(leg_id="L1", leg_name="Leg1", nodes=[node])
    state = ProjectState(
        legs=[leg],
        special_profile=SpecialReportProfile(forbid_na=True),
    )
    labels = state_has_forbidden_na(state)
    assert labels == ["Leg1 / 试验A"]
