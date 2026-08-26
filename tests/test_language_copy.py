"""Seam 2: language-side copy helpers (conclusions, join, application EN, photo captions)."""

from src.language_copy import (
    english_from_application,
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

    assert format_conclusion(TestResult.PASS, "中英文") == "合格 / Pass"
    assert format_conclusion(TestResult.FAIL, "中英文") == "不合格 / Fail"
    assert format_conclusion(TestResult.NA, "中英文") == "N/A"


def test_format_conclusion_accepts_string_aliases():
    assert format_conclusion("合格", "英文") == "Pass"
    assert format_conclusion("Pass", "中文") == "合格"
    assert format_conclusion("不合格", "英文") == "Fail"
    assert format_conclusion("Fail", "中英文") == "不合格 / Fail"


def test_language_text_join_and_no_english_fallback():
    assert language_text("高温", "High temp", "中英文") == "高温 / High temp"
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
