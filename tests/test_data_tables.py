import tempfile
from pathlib import Path

from openpyxl import load_workbook

from src.io.data_tables import (
    DataTableError,
    attachment_dir,
    create_blank_workbook,
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
