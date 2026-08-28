"""Seam 2: language-side copy helpers (conclusions, join, application EN, photo captions)."""

from src.language_copy import (
    english_from_application,
    field_label,
    format_conclusion,
    is_custom_photo_stem,
    language_text,
    photo_caption,
)
from src.models.project_state import TestResult


def test_format_conclusion_zh_en_bilingual():
    assert format_conclusion(TestResult.PASS, "中文") == "合格"
    assert format_conclusion(TestResult.FAIL, "中文") == "不合格"
    assert format_conclusion(TestResult.NA, "中文") == "N/A"

    assert format_conclusion(TestResult.PASS, "英文") == "Pass"
    assert format_conclusion(TestResult.FAIL, "英文") == "Fail"
    assert format_conclusion(TestResult.NA, "英文") == "N/A"

    assert format_conclusion(TestResult.PASS, "中英文") == "合格/Pass"
    assert format_conclusion(TestResult.FAIL, "中英文") == "不合格/Fail"
    assert format_conclusion(TestResult.NA, "中英文") == "N/A"


def test_format_conclusion_accepts_string_aliases():
    assert format_conclusion("合格", "英文") == "Pass"
    assert format_conclusion("Pass", "中文") == "合格"
    assert format_conclusion("不合格", "英文") == "Fail"
    assert format_conclusion("Fail", "中英文") == "不合格/Fail"


def test_language_text_join_and_no_english_fallback():
    assert language_text("高温", "High temp", "中英文") == "高温 / High temp"
    assert language_text("VW316-6 FCA", "VW316-6 FCA", "中英文") == "VW316-6 FCA"
    assert language_text("6710820", "6710820", "中英文") == "6710820"
    assert language_text("高温", "", "中英文") == "高温"
    assert language_text("", "High temp", "中英文") == "High temp"
    assert language_text("", "", "中英文") == ""

    assert language_text("高温", "High temp", "中文") == "高温"
    assert language_text("高温", "", "中文") == "高温"

    assert language_text("高温", "High temp", "英文") == "High temp"
    assert language_text("高温", "", "英文") == ""
    assert language_text("", "", "英文") == ""


def test_english_from_application_no_han_usable_as_en():
    assert english_from_application("P519 KAB LHD", "") == "P519 KAB LHD"
    assert english_from_application("ADCU8", "") == "ADCU8"
    assert english_from_application("42", "") == "42"
    assert english_from_application("黑色", "") == ""
    assert english_from_application("黑色Black", "Black") == "Black"
    assert english_from_application("成品", "Finished products") == "Finished products"
    assert english_from_application("", "") == ""
    # Han in the EN slot is not usable English (e.g. mis-resolved 同申请公司)
    assert english_from_application("中文公司", "中文公司") == ""
    assert english_from_application("中文地址", "上海市某某路") == ""


def test_photo_caption_template_albums_by_language():
    assert photo_caption("试验前", "中文") == "试验前"
    assert photo_caption("试验中", "中文") == "试验中"
    assert photo_caption("试验后", "中文") == "试验后"

    assert photo_caption("试验前", "英文") == "Before test"
    assert photo_caption("试验中", "英文") == "Test setup"
    assert photo_caption("试验后", "英文") == "After test"

    assert photo_caption("试验前", "中英文") == "试验前 / Before test"
    assert photo_caption("试验中", "中英文") == "试验中 / Test setup"
    assert photo_caption("试验后", "中英文") == "试验后 / After test"


def test_photo_caption_default_stem_keeps_album_caption():
    assert photo_caption("试验前", "英文", file_stem="试验前-001") == "Before test"
    assert photo_caption("试验中", "中文", file_stem="试验中-012") == "试验中"
    assert not is_custom_photo_stem("试验前", "试验前-001")


def test_photo_caption_custom_stem_overrides():
    assert is_custom_photo_stem("试验前", "setup-left")
    assert photo_caption("试验前", "英文", file_stem="setup-left") == "setup-left"
    assert photo_caption("试验前", "中文", file_stem="现场布置") == "现场布置"
    assert photo_caption("试验前", "中英文", file_stem="custom") == "custom"


def test_photo_caption_data_and_unknown_use_filename():
    assert photo_caption("数据", "中文", file_stem="曲线-001") == "曲线-001"
    assert photo_caption("数据", "英文", file_stem="curve") == "curve"
    assert photo_caption("数据", "中英文") == ""
    assert photo_caption("预处理", "英文", file_stem="pre-01") == "pre-01"
    assert photo_caption("自定义夹", "中文") == ""


def test_field_label_overview_and_dates_match_application_phrasing():
    assert field_label("申请单号", "中文") == "申请单号"
    assert field_label("申请单号", "英文") == "Application No."
    assert field_label("申请公司", "英文") == "Applicant Name"
    assert field_label("申请公司地址", "英文") == "Applicant Address"
    assert field_label("报告抬头公司", "英文") == "Company shown on report"
    assert field_label("报告抬头地址", "英文") == "Address shown on report"
    assert field_label("样品名称", "英文") == "Sample Name"

    assert field_label("样品接收日期", "中文") == "样品接收日期"
    assert field_label("样品接收日期", "英文") == "Sample Received Date"
    assert field_label("样品检测日期", "中英文") == "样品检测日期Testing Period"

    # Date-bar labels are independent of the report period wording
    assert field_label("检测开始", "中文") == "试验开始"
    assert field_label("检测开始", "英文") == "Test Start"
    assert field_label("检测结束", "中文") == "试验结束"
    assert field_label("检测结束", "英文") == "Test End"
    assert field_label("检测天数", "中文") == "天数"
    assert field_label("检测天数", "英文") == "Days"

    assert field_label("颜色", "英文") == "Color"
    assert field_label("材料编号", "英文") == "Material Code"
    assert field_label("材质", "英文") == "Material"
    assert field_label("材料牌号", "英文") == "Material Trademark"
    assert field_label("生产日期", "英文") == "Production Date"
    assert field_label("样品批号", "英文") == "Sample Batch"

    assert field_label("未知键", "中文") == "未知键"
    assert field_label("未知键", "英文") == ""
