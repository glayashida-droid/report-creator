import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook

from src.io.data_tables import (
    DataTableError,
    attachment_dir,
    create_blank_workbook,
    read_preview_snapshot,
    upload_existing_xlsx,
)
from src.models.project_state import DataTableRef, ProjectState, TestLeg, TestNode


def test_create_blank_workbook_writes_xlsx_and_returns_ref():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ref = create_blank_workbook(root, "高温试验", "工况记录")
        assert ref.title == "工况记录"
        path = root / ref.relative_path
        assert path.is_file()
        assert path.suffix.lower() == ".xlsx"
        assert path.parent == attachment_dir(root, "高温试验")
        wb = load_workbook(path)
        assert wb.sheetnames
        wb.close()


def test_create_blank_rejects_unusable_test_name():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            create_blank_workbook(root, "请选择试验...", "表")
            raise AssertionError("expected DataTableError")
        except DataTableError:
            pass
        assert not (root / "3.测试组").exists()


def test_create_blank_unique_filename_does_not_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = create_blank_workbook(root, "高温试验", "表A")
        second = create_blank_workbook(root, "高温试验", "表A")
        assert first.relative_path != second.relative_path
        assert (root / first.relative_path).is_file()
        assert (root / second.relative_path).is_file()


def test_data_table_index_round_trips_in_project_json():
    state = ProjectState(project_id="P1")
    node = TestNode(
        test_name="高温试验",
        data_tables=[
            DataTableRef(title="工况记录", relative_path="3.测试组/高温试验/数据表附件/工况记录.xlsx")
        ],
    )
    state.legs.append(TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[node]))
    path = Path(".scratch/test_data_tables_state.json")
    state.save_to_file(str(path))
    try:
        loaded = ProjectState.load_from_file(str(path))
        refs = loaded.legs[0].nodes[0].data_tables
        assert len(refs) == 1
        assert refs[0].title == "工况记录"
        assert refs[0].relative_path == "3.测试组/高温试验/数据表附件/工况记录.xlsx"
    finally:
        if path.exists():
            path.unlink()


def _write_bbox_fixture(path: Path) -> None:
    """3x2 used area with a hole at B2 and a merge on row 3."""
    wb = Workbook()
    ws = wb.active
    ws.title = "数据"
    ws["A1"] = "列甲"
    ws["B1"] = "列乙"
    ws["C1"] = "列丙"
    ws["A2"] = 10
    # B2 left empty on purpose
    ws["C2"] = 30
    ws.merge_cells("A3:B3")
    ws["A3"] = "合并区"
    wb.save(path)
    wb.close()


def test_upload_copies_xlsx_and_titles_from_filename():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = Path(tmp) / "outside" / "工况记录表.xlsx"
        src.parent.mkdir()
        _write_bbox_fixture(src)
        ref = upload_existing_xlsx(root, "高温试验", src)
        assert ref.title == "工况记录表.xlsx"
        dest = root / ref.relative_path
        assert dest.is_file()
        assert dest.parent == attachment_dir(root, "高温试验")
        assert dest.name == "工况记录表.xlsx"
        assert dest.read_bytes() == src.read_bytes()


def test_upload_same_name_gets_suffix_not_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = Path(tmp) / "outside" / "同名.xlsx"
        src.parent.mkdir()
        _write_bbox_fixture(src)
        first = upload_existing_xlsx(root, "高温试验", src)
        second = upload_existing_xlsx(root, "高温试验", src)
        assert first.title == "同名.xlsx"
        assert second.title == "同名.xlsx"
        assert first.relative_path != second.relative_path
        assert (root / first.relative_path).is_file()
        assert (root / second.relative_path).is_file()


def test_upload_then_preview_snapshot_keeps_bbox_empties():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = Path(tmp) / "outside" / "夹具.xlsx"
        src.parent.mkdir()
        _write_bbox_fixture(src)
        ref = upload_existing_xlsx(root, "高温试验", src)
        snap = read_preview_snapshot(root / ref.relative_path)
        assert snap.values == [
            ["列甲", "列乙", "列丙"],
            ["10", "", "30"],
            ["合并区", "", ""],
        ]
        assert "A3:B3" in snap.merges


def test_preview_snapshot_is_bbox_keeps_empty_cells_and_merges():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.xlsx"
        _write_bbox_fixture(path)
        snap = read_preview_snapshot(path)
        assert snap.sheet_name == "数据"
        assert snap.values == [
            ["列甲", "列乙", "列丙"],
            ["10", "", "30"],
            ["合并区", "", ""],
        ]
        assert "A3:B3" in snap.merges


def test_preview_refresh_rereads_disk_changes():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "live.xlsx"
        _write_bbox_fixture(path)
        before = read_preview_snapshot(path)
        assert before.values[1][2] == "30"

        wb = load_workbook(path)
        ws = wb.active
        ws["C2"] = 99
        ws["D1"] = "列丁"
        wb.save(path)
        wb.close()

        after = read_preview_snapshot(path)
        assert after.values[0] == ["列甲", "列乙", "列丙", "列丁"]
        assert after.values[1][2] == "99"
        assert after.values != before.values


if __name__ == "__main__":
    test_create_blank_workbook_writes_xlsx_and_returns_ref()
    test_create_blank_rejects_unusable_test_name()
    test_create_blank_unique_filename_does_not_overwrite()
    test_data_table_index_round_trips_in_project_json()
    test_upload_copies_xlsx_and_titles_from_filename()
    test_upload_same_name_gets_suffix_not_overwrite()
    test_upload_then_preview_snapshot_keeps_bbox_empties()
    test_preview_snapshot_is_bbox_keeps_empty_cells_and_merges()
    test_preview_refresh_rereads_disk_changes()
    print("test_data_tables: ok")