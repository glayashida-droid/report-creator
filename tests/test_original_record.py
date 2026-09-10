"""Tests for original-record Word export."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import _Cell
from openpyxl import Workbook

from src.generators.original_record import (
    OriginalRecordData,
    default_output_path,
    format_id_range,
    format_share_path_for_record,
    format_test_period,
    generate_original_record,
    resolve_original_record_folder,
    resolve_original_record_template,
    stack_standard_blocks,
)
from src.io.test_photos import TEST_GROUP_DIR
from src.models.project_state import (
    DataTableRef as DataRef,
    TestEquipment as EqModel,
    TestStandard as StdModel,
)

TEMPLATE = Path("templates/original_data_sheet/original_record_placeholders.docx")


def test_resolve_template_falls_back_local():
    path = resolve_original_record_template()
    assert path.is_file()
    assert path.name == "original_record_placeholders.docx"


def test_format_helpers():
    assert format_id_range(["A01", "A02", "A03"]) == "A01~A03"
    assert format_id_range(["A01", "B02"]) == "A01、B02"
    assert format_test_period("2026-09-08", "2026-09-09") == "2026.09.08~2026.09.09"
    assert format_share_path_for_record(
        "/Volumes/材料实验室b/车载电子/2026年/foo",
        smb_hint="smb://10.10.31.8/材料实验室b/车载电子",
    ) == r"\\10.10.31.8\材料实验室b\车载电子\2026年\foo"


def test_stack_standard_blocks():
    stds = [
        StdModel(test_name="盐雾", standard_desc="条件A", evaluation_req="要求A"),
        StdModel(test_name="湿热", standard_desc="条件B", evaluation_req="要求B"),
    ]
    text = stack_standard_blocks(stds, "standard_desc")
    assert "盐雾" in text and "条件A" in text
    assert "湿热" in text and "条件B" in text


def test_resolve_original_record_folder_prefers_remote(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    remote.mkdir()
    folder = resolve_original_record_folder(
        local, remote, leg_name="Leg 1", test_item="沙尘试验"
    )
    assert folder == remote / TEST_GROUP_DIR / "Leg 1-沙尘试验"


def test_resolve_original_record_folder_falls_back_local(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    folder = resolve_original_record_folder(
        local, tmp_path / "missing", leg_name="Leg 1", test_item="沙尘试验"
    )
    assert folder == local / TEST_GROUP_DIR / "Leg 1-沙尘试验"


def test_resolve_original_record_folder_requires_roots_and_names(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    assert resolve_original_record_folder(None, None, leg_name="Leg 1", test_item="沙尘") is None
    assert resolve_original_record_folder(root, None, leg_name="", test_item="沙尘") is None
    assert (
        resolve_original_record_folder(root, None, leg_name="Leg 1", test_item="请选择试验...")
        is None
    )


def test_default_output_path_saves_beside_albums(tmp_path: Path):
    folder = tmp_path / TEST_GROUP_DIR / "Leg 1-沙尘试验"
    (folder / "试验前").mkdir(parents=True)
    path = default_output_path(folder, application_no="A1", test_item="沙尘试验")
    assert path.parent == folder
    assert path.name == "A1_沙尘试验_原始记录.docx"
    assert not (tmp_path / "原始记录").exists()
    assert not (folder / "原始记录").exists()
    first = default_output_path(folder, application_no="A1", test_item="沙尘试验")
    first.write_bytes(b"x")
    second = default_output_path(folder, application_no="A1", test_item="沙尘试验")
    assert second.name == "A1_沙尘试验_原始记录-2.docx"


def test_generate_original_record_fills_and_expands(tmp_path: Path):
    assert TEMPLATE.is_file()
    data = OriginalRecordData(
        application_no="A22606909401",
        test_item="Dust test",
        test_method="VW82511-2010 / 8.3.6",
        sample_name="控制器",
        sample_ids=["A22606909401-A01", "A22606909401-A02"],
        env_condition="23℃ / 50%RH",
        start_date="2026-09-08",
        end_date="2026-09-08",
        share_path=r"\\10.10.31.8\材料实验室b\车载电子\proj",
        equipments=[
            EqModel(name="沙尘箱", model="M1", code="TTE-001", valid_date="2027-01-01"),
            EqModel(name="温箱", model="M2", code="TTE-002", valid_date="2027-02-01"),
        ],
        standards=[
            StdModel(
                test_name="沙尘试验",
                standard_desc="粉尘浓度 …",
                evaluation_req="外观无异常",
            ),
            StdModel(
                test_name="功能检查",
                standard_desc="通电检查",
                evaluation_req="功能正常",
            ),
        ],
        tester_name="张三",
    )
    out = tmp_path / "out.docx"
    generate_original_record(data, out, template_path=TEMPLATE)
    assert out.is_file()

    doc = Document(str(out))
    blob = "\n".join(p.text for p in doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for tc in row._tr.tc_lst:
                blob += "\n" + _Cell(tc, table).text

    assert "A22606909401" in blob
    assert "Dust test" in blob
    assert "控制器" in blob
    assert "A22606909401-A01~A22606909401-A02" in blob
    assert "23℃ / 50%RH" in blob
    assert "张三" in blob
    assert "沙尘箱" in blob and "温箱" in blob
    assert "沙尘试验" in blob and "功能检查" in blob
    assert "{{申请单编号}}" not in blob
    assert "{{设备名称}}" not in blob
    assert "{{试验项目}}" not in blob
    assert "{{结果样品编号}}" not in blob
    assert "{{RESULT_TABLE}}" not in blob
    assert "{{DATA_TABLES}}" not in blob
    assert "{{" not in blob
    assert any(p.text.strip() == "/" for p in doc.paragraphs)

    resultish = [
        t
        for t in doc.tables
        if any(
            "试验前" in _Cell(tc, t).text
            for row in t.rows
            for tc in row._tr.tc_lst
        )
    ]
    assert len(resultish) == 2
    merge_cols = _template_result_merge_cols()
    for t in resultish:
        starts = sum(
            1
            for row in t.rows
            for tc in row._tr.tc_lst
            if _Cell(tc, t).text.strip() == "试验前"
            or _Cell(tc, t).text.strip().startswith("试验前")
        )
        assert starts == 2
        _assert_sample_block_vmerges(t, merge_cols)


def _vmerge_val(tc) -> str | None:
    tcPr = tc.tcPr
    if tcPr is None:
        return None
    vm = tcPr.find(qn("w:vMerge"))
    if vm is None:
        return None
    return vm.get(qn("w:val")) or "continue"


def _result_sample_starts(table) -> list[int]:
    starts: list[int] = []
    for i, row in enumerate(table.rows):
        texts = [_Cell(tc, table).text.strip() for tc in row._tr.tc_lst]
        if any(t == "试验前" or t.startswith("试验前") for t in texts):
            starts.append(i)
    return starts


def _template_result_merge_cols() -> list[int]:
    doc = Document(str(TEMPLATE))
    table = next(
        t
        for t in doc.tables
        if any(
            "试验前" in _Cell(tc, t).text
            for row in t.rows
            for tc in row._tr.tc_lst
        )
    )
    start = _result_sample_starts(table)[0]
    cols = [
        ci
        for ci, tc in enumerate(table.rows[start]._tr.tc_lst)
        if _vmerge_val(tc) is not None
    ]
    # 样品编号 / 功能等级 / 结论
    assert cols[:1] == [0] and len(cols) >= 3
    return cols


def _assert_sample_block_vmerges(table, merge_cols: list[int]) -> None:
    starts = _result_sample_starts(table)
    assert starts
    for start in starts:
        for offset, expected in ((0, "restart"), (1, "continue"), (2, "continue")):
            tcs = table.rows[start + offset]._tr.tc_lst
            for ci in merge_cols:
                assert _vmerge_val(tcs[ci]) == expected, (
                    f"sample@{start} row+{offset} col {ci}: "
                    f"expected vMerge={expected}, got {_vmerge_val(tcs[ci])}"
                )


def _write_simple_xlsx(path: Path, *, with_limit: bool, limit_value: str = "") -> None:
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "样品编号"
    ws["B1"] = "读数"
    if with_limit:
        ws["A2"] = "限值"
        ws["B2"] = limit_value
        ws["A3"] = "A01"
        ws["B3"] = "1.0"
    else:
        ws["A2"] = "A01"
        ws["B2"] = "1.0"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    wb.close()


def test_generate_original_record_data_tables_titles_and_limit_flag(tmp_path: Path):
    project = tmp_path / "proj"
    x1 = project / "t1.xlsx"
    x2 = project / "t2.xlsx"
    _write_simple_xlsx(x1, with_limit=True, limit_value="≤2")
    _write_simple_xlsx(x2, with_limit=False)

    refs = [
        DataRef(
            title="5点法",
            relative_path=str(x1.relative_to(project)),
            include_limit_row_in_report=True,
        ),
        DataRef(
            title="工况",
            relative_path=str(x2.relative_to(project)),
            include_limit_row_in_report=False,
        ),
    ]
    data = OriginalRecordData(
        application_no="A1",
        test_item="Dust",
        sample_ids=["A01"],
        project_path=str(project),
        leg_name="Leg1",
        data_tables=refs,
        standards=[StdModel(test_name="沙尘")],
    )
    out = tmp_path / "with_tables.docx"
    generate_original_record(data, out, template_path=TEMPLATE)
    doc = Document(str(out))
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    assert "5点法" in paras
    assert "工况" in paras
    assert "{{DATA_TABLES}}" not in "\n".join(paras)

    joined = "\n---\n".join(
        "\n".join(_Cell(tc, t).text for row in t.rows for tc in row._tr.tc_lst)
        for t in doc.tables
    )
    assert "限值" in joined
    assert "≤2" in joined
    assert "读数" in joined
    assert "1.0" in joined


def test_generate_original_record_omits_limit_when_unchecked(tmp_path: Path):
    project = tmp_path / "proj"
    x1 = project / "t1.xlsx"
    _write_simple_xlsx(x1, with_limit=True, limit_value="≤2")
    refs = [
        DataRef(
            title="5点法",
            relative_path=str(x1.relative_to(project)),
            include_limit_row_in_report=False,
        )
    ]
    data = OriginalRecordData(
        test_item="Dust",
        project_path=str(project),
        data_tables=refs,
        standards=[StdModel(test_name="沙尘")],
    )
    out = tmp_path / "no_limit.docx"
    generate_original_record(data, out, template_path=TEMPLATE)
    doc = Document(str(out))
    joined = "\n".join(
        _Cell(tc, t).text for t in doc.tables for row in t.rows for tc in row._tr.tc_lst
    )
    assert "限值" not in joined
    assert "≤2" not in joined
    assert "1.0" in joined
