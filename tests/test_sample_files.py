from pathlib import Path

from src.io.sample_files import (
    APPLICATION_NAME_MISMATCH_HINT,
    APPLICATION_NOT_FOUND_HINT,
    application_not_found_hint,
    find_application_excel,
    find_quotation_pdf,
    find_sample_files,
    project_id_match_tokens,
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK")
    return path


def test_tokens_include_application_no_prefix():
    assert project_id_match_tokens("A2260664782101") == [
        "A2260664782101",
        "A22606647821",
    ]
    assert project_id_match_tokens("A22606647821") == ["A22606647821"]


def test_picks_application_xlsx_matching_project_id(tmp_path: Path):
    sample = tmp_path / "1.接样组"
    wanted = _touch(sample / "A22606647821.xlsx")
    _touch(sample / "KX21-电子换挡器零部件试验清单.xlsx")
    _touch(sample / "~$A22606647821.xlsx")

    found = find_application_excel(tmp_path, "A2260664782101")
    assert found == wanted


def test_accepts_updated_application_filename(tmp_path: Path):
    sample = tmp_path / "1.接样组"
    wanted = _touch(sample / "A22604379701--申请表更新.xlsx")
    _touch(sample / "试验清单.xlsx")

    found = find_application_excel(tmp_path, "A2260437970101")
    assert found == wanted


def test_does_not_pick_unrelated_xlsx(tmp_path: Path):
    sample = tmp_path / "1.接样组"
    _touch(sample / "KX21-试验清单.xlsx")
    _touch(sample / "A22609990001.xlsx")

    assert find_application_excel(tmp_path, "A2260664782101") is None


def test_does_not_match_longer_different_id(tmp_path: Path):
    sample = tmp_path / "1.接样组"
    _touch(sample / "A2260664782199.xlsx")

    assert find_application_excel(tmp_path, "A2260664782101") is None


def test_prefers_exact_application_no_over_suffixed_name(tmp_path: Path):
    sample = tmp_path / "1.接样组"
    wanted = _touch(sample / "A22606647821.xlsx")
    _touch(sample / "A22606647821--申请表更新.xlsx")

    found = find_application_excel(tmp_path, "A2260664782101")
    assert found == wanted


def test_find_sample_files_keeps_quote_pdf(tmp_path: Path):
    sample = tmp_path / "1.接样组"
    excel = _touch(sample / "A22606647821.xlsx")
    quote = _touch(sample / "宁波正朗 测试报价单-KX21.pdf")
    _touch(sample / "KX21-ELP测试计划.pdf")

    app, pdf = find_sample_files(tmp_path, "A2260664782101")
    assert app == excel
    assert pdf == quote
    assert find_quotation_pdf(tmp_path) == quote


def test_finds_quotation_by_cti_quote_number_filename(tmp_path: Path):
    sample = tmp_path / "1.接样组"
    sample.mkdir(parents=True)
    quote = sample / "SZV2607242479701 厦门海拉--防尘防水.pdf"
    quote.write_bytes(
        Path(
            "data/A2260028017801/1.接样组/SZV2607242479701 厦门海拉--防尘防水.pdf"
        ).read_bytes()
    )
    _touch(sample / "参考报告-A225036644650100001E.pdf")

    assert find_quotation_pdf(tmp_path) == quote


def test_hint_when_xlsx_uses_another_project_id(tmp_path: Path):
    _touch(tmp_path / "1.接样组" / "A22600280175.xlsx")

    assert find_application_excel(tmp_path, "A2220011234567") is None
    assert (
        application_not_found_hint(tmp_path, "A2220011234567")
        == APPLICATION_NAME_MISMATCH_HINT
    )
    assert APPLICATION_NAME_MISMATCH_HINT == "申请单和文件夹不同名，未加载成功"


def test_hint_when_no_application_xlsx(tmp_path: Path):
    _touch(tmp_path / "1.接样组" / "KX21-试验清单.xlsx")

    assert (
        application_not_found_hint(tmp_path, "A2220011234567")
        == APPLICATION_NOT_FOUND_HINT
    )


def test_hint_empty_when_application_xlsx_matches(tmp_path: Path):
    _touch(tmp_path / "1.接样组" / "A22600280175.xlsx")

    assert application_not_found_hint(tmp_path, "A2260028017501") == ""


def test_overview_box_shows_name_mismatch_instead_of_unloaded():
    import sys

    from PySide6.QtWidgets import QApplication, QLabel

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    win = MainWindow()
    win._application_load_hint = APPLICATION_NAME_MISMATCH_HINT
    win.refresh_overview_ui()
    labels = [
        win.info_form.itemAt(i).widget().text()
        for i in range(win.info_form.count())
        if isinstance(win.info_form.itemAt(i).widget(), QLabel)
    ]
    assert APPLICATION_NAME_MISMATCH_HINT in labels
    assert "未加载" not in labels
    win.close()
