from pathlib import Path

from src.io.to_numbers import (
    apply_autoliv_to_numbers,
    extract_to_numbers_from_application,
    extract_to_numbers_from_text,
    format_to_numbers_display,
    is_autoliv_applicant,
)
from src.models.project_state import ProjectState

SAMPLE_XLSX = Path(__file__).resolve().parents[1] / "database" / "A22606909401.xlsx"

H3 = (
    "报告体现TO-26112398-04；实验前后测三路电阻，他们做之前我再跟他们沟通下，"
    "另外样件送过去的时尽量保护的好些哈，避免划伤、碰伤，谢谢！先震Z向 再XY\n"
    "整车管柱角度25.8\n需电器连接（1.INF 2.INF）"
)


def test_extracts_to_from_special_requirement_prose():
    assert extract_to_numbers_from_text(H3) == ["TO-26112398-04"]
    assert extract_to_numbers_from_text("无特殊要求 / Per spec") == []
    assert extract_to_numbers_from_text("to-1234 and TO-1234-01") == [
        "TO-1234",
        "TO-1234-01",
    ]


def test_compact_display_collapses_same_middle_digits():
    assert (
        format_to_numbers_display(
            ["TO-1234-01", "TO-1234-02", "TO-1234-03"]
        )
        == "TO-1234-01/02/03"
    )
    assert (
        format_to_numbers_display(
            ["TO-26112398-04", "TO-26112398-05", "TO-26112398-06"]
        )
        == "TO-26112398-04/05/06"
    )
    assert format_to_numbers_display(["TO-1234", "TO-5678-01"]) == "TO-1234，TO-5678-01"


def test_autoliv_gate():
    assert is_autoliv_applicant("奥托立夫（上海）汽车安全系统研发有限公司")
    assert not is_autoliv_applicant("均胜")


def test_real_autoliv_application_extracts_three_tos():
    raw = SAMPLE_XLSX.read_bytes()
    assert extract_to_numbers_from_application(raw) == [
        "TO-26112398-04",
        "TO-26112398-05",
        "TO-26112398-06",
    ]


def test_apply_only_when_applicant_is_autoliv():
    raw = SAMPLE_XLSX.read_bytes()
    autoliv = ProjectState(
        project_id="A22606909401",
        applicant_name="奥托立夫（上海）汽车安全系统研发有限公司",
    )
    apply_autoliv_to_numbers(autoliv, raw)
    assert autoliv.to_numbers == [
        "TO-26112398-04",
        "TO-26112398-05",
        "TO-26112398-06",
    ]
    assert autoliv.to_numbers_display == "TO-26112398-04/05/06"

    other = ProjectState(project_id="X", applicant_name="均胜")
    other.to_numbers = ["TO-1-01"]
    other.to_numbers_display = "TO-1-01"
    apply_autoliv_to_numbers(other, raw)
    assert other.to_numbers == []
    assert other.to_numbers_display == ""
