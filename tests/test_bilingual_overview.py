"""TKT-2: bilingual overview / edit_language on ProjectState (no GUI)."""

from pathlib import Path

from application_parser.models import ApplicationData, FileSource
from src.application_ingest import apply_application_data
from src.models.project_state import ProjectState


def _app_data(**kwargs) -> ApplicationData:
    base = dict(
        source=FileSource(file_type="application", filename="a.xlsx"),
        applicant_name="采埃孚汽车系统(上海)有限公司",
        applicant_address="上海市某某路1号",
        applicant_name_cn="采埃孚汽车系统(上海)有限公司",
        applicant_name_en="ZF Automotive Systems (Shanghai) Co., Ltd.",
        applicant_address_cn="上海市某某路1号",
        applicant_address_en="No.1 Somewhere Rd, Shanghai",
        report_title_name_cn="抬头公司",
        report_title_name_en="Title Co.",
        report_title_address_cn="抬头地址",
        report_title_address_en="Title Addr",
        sample_info={
            "申请单号": "A22604379701",
            "样品名称": "安全带",
            "零件号": "P519 KAB LHD",
            "样品状态": "黑色",
        },
        sample_info_candidates={
            "申请单号": ["A22604379701"],
            "样品名称": ["安全带", "Seat belt"],
            "零件号": ["P519 KAB LHD"],
            "样品状态": ["黑色", "Black"],
        },
    )
    base.update(kwargs)
    return ApplicationData(**base)


def test_apply_application_keeps_cn_and_en_sides():
    state = ProjectState(project_id="A1")
    apply_application_data(state, _app_data())

    assert state.applicant_name == "采埃孚汽车系统(上海)有限公司"
    assert state.applicant_name_en == "ZF Automotive Systems (Shanghai) Co., Ltd."
    assert state.applicant_address_en == "No.1 Somewhere Rd, Shanghai"
    assert state.report_title_name == "抬头公司"
    assert state.report_title_name_en == "Title Co."
    assert state.application_fields["样品名称"] == "安全带"
    assert state.application_fields_en["样品名称"] == "Seat belt"
    assert state.application_fields_en["零件号"] == "P519 KAB LHD"
    assert state.application_fields_en["样品状态"] == "Black"
    assert state.sample_name == "安全带"
    assert state.sample_name_en == "Seat belt"


def test_overview_switches_with_edit_language_and_persists_both_sides(tmp_path):
    state = ProjectState(project_id="A1")
    apply_application_data(state, _app_data())
    state.edit_language = "中文"
    zh_rows = dict(state.iter_overview_fields())
    assert zh_rows["申请公司"] == "采埃孚汽车系统(上海)有限公司"
    assert zh_rows["样品名称"] == "安全带"
    assert zh_rows["零件号"] == "P519 KAB LHD"

    state.edit_language = "英文"
    en_rows = dict(state.iter_overview_fields())
    assert en_rows["申请公司"] == "ZF Automotive Systems (Shanghai) Co., Ltd."
    assert en_rows["样品名称"] == "Seat belt"
    assert en_rows["零件号"] == "P519 KAB LHD"

    state.set_overview_value("样品名称", "Seat belt (edited)")
    assert state.sample_name_en == "Seat belt (edited)"
    assert state.application_fields["样品名称"] == "安全带"

    state.edit_language = "中文"
    state.set_overview_value("样品名称", "安全带改")
    assert state.sample_name == "安全带改"
    assert state.sample_name_en == "Seat belt (edited)"

    path = Path(tmp_path) / "state.json"
    state.save_to_file(str(path))
    loaded = ProjectState.load_from_file(str(path))
    assert loaded.sample_name == "安全带改"
    assert loaded.sample_name_en == "Seat belt (edited)"
    assert loaded.applicant_name_en.startswith("ZF")
    loaded.edit_language = "英文"
    assert dict(loaded.iter_overview_fields())["样品名称"] == "Seat belt (edited)"


def test_english_overview_shows_empty_when_cn_present_but_en_missing():
    state = ProjectState(
        project_id="A1",
        edit_language="英文",
        applicant_name="仅中文公司",
        applicant_name_en="",
        application_fields={"申请公司": "仅中文公司", "主机厂": "某某"},
        application_fields_en={},
    )
    rows = dict(state.iter_overview_fields())
    assert rows["申请公司"] == ""
    assert rows["主机厂"] == ""


def test_han_only_sample_value_has_empty_english_side():
    state = ProjectState(project_id="A1")
    apply_application_data(
        state,
        _app_data(
            sample_info={"颜色": "黑色"},
            sample_info_candidates={"颜色": ["黑色"]},
        ),
    )
    assert state.application_fields["颜色"] == "黑色"
    assert state.application_fields_en.get("颜色", "") == ""
