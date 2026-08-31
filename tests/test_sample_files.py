from pathlib import Path

from src.io.sample_files import (
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
