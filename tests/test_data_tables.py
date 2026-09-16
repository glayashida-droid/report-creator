import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

from src.io.data_tables import (
    DataTableError,
    PreviewSnapshot,
    attachment_dir,
    content_column_groups,
    copy_from_template,
    create_blank_workbook,
    decimal_places,
    delete_attachment,
    find_bound_row_indices,
    find_decimal_inconsistencies,
    find_out_of_range,
    find_out_of_range_by_limits,
    has_limit_row,
    import_sample_ids,
    infer_header_row_count,
    sync_display_layout,
    list_attachment_refs,
    list_data_table_templates,
    open_attachment,
    parse_numeric_display,
    prepare_display_snapshot,
    read_preview_snapshot,
    resolve_open_argv,
    retarget_node_data_tables,
    rewrite_test_dir_in_relative_path,
    slice_preview_snapshot,
    split_preview_snapshot_for_page,
    upload_existing_xlsx,
    value_violates_limit,
    LimitRule,
)
from src.io.test_photos import test_dir_key as leg_test_dir_key
from src.models.project_state import DataTableRef, ProjectState, TestLeg, TestNode

LEG = "Leg 1"


def test_create_blank_workbook_writes_xlsx_and_returns_ref():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ref = create_blank_workbook(root, LEG, "高温试验", "工况记录")
        assert ref.title == "工况记录"
        path = root / ref.relative_path
        assert path.is_file()
        assert path.suffix.lower() == ".xlsx"
        assert path.parent == attachment_dir(root, LEG, "高温试验")
        assert ref.relative_path == (
            f"3.测试组/{leg_test_dir_key(LEG, '高温试验')}/数据表附件/工况记录.xlsx"
        )
        wb = load_workbook(path)
        assert wb.sheetnames
        wb.close()


def test_create_blank_rejects_unusable_test_name():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            create_blank_workbook(root, LEG, "请选择试验...", "表")
            raise AssertionError("expected DataTableError")
        except DataTableError:
            pass
        assert not (root / "3.测试组").exists()


def test_create_blank_unique_filename_does_not_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = create_blank_workbook(root, LEG, "高温试验", "表A")
        second = create_blank_workbook(root, LEG, "高温试验", "表A")
        assert first.relative_path != second.relative_path
        assert (root / first.relative_path).is_file()
        assert (root / second.relative_path).is_file()


def test_list_attachment_refs_scans_sorted_by_filename_skips_temp():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = attachment_dir(root, LEG, "高温试验")
        folder.mkdir(parents=True)
        (folder / "zeta.xlsx").write_bytes(b"PK")
        (folder / "Alpha.xlsx").write_bytes(b"PK")
        (folder / "~$Alpha.xlsx").write_bytes(b"PK")
        (folder / "notes.txt").write_text("x", encoding="utf-8")
        # Valid minimal xlsx via create for one; others are fake but list only checks suffix
        create_blank_workbook(root, LEG, "高温试验", "中间表")

        refs = list_attachment_refs(root, LEG, "高温试验")
        titles = [r.title for r in refs]
        assert titles == sorted(titles, key=lambda t: t.casefold())
        assert "Alpha" in titles
        assert "zeta" in titles
        assert "中间表" in titles
        assert "~$Alpha" not in titles
        assert all(r.relative_path.endswith(".xlsx") for r in refs)
        assert all("/数据表附件/" in r.relative_path for r in refs)


def test_list_attachment_refs_empty_or_missing_folder():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        assert list_attachment_refs(root, LEG, "高温试验") == []
        assert list_attachment_refs(root, "", "高温试验") == []
        assert list_attachment_refs(root, LEG, "请选择试验...") == []


def test_list_attachment_refs_picks_up_manually_dropped_file():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Stale index path would not matter — scan finds the real file.
        folder = attachment_dir(root, LEG, "高温试验")
        folder.mkdir(parents=True)
        dest = folder / "三路电阻.xlsx"
        wb = Workbook()
        wb.save(dest)
        wb.close()
        refs = list_attachment_refs(root, LEG, "高温试验")
        assert len(refs) == 1
        assert refs[0].title == "三路电阻"
        assert (root / refs[0].relative_path).is_file()


def test_data_table_index_round_trips_in_project_json():
    state = ProjectState(project_id="P1")
    node = TestNode(
        test_name="高温试验",
        data_tables=[
            DataTableRef(
                title="工况记录",
                relative_path="3.测试组/Leg 1-高温试验/数据表附件/工况记录.xlsx",
            )
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
        assert refs[0].relative_path == "3.测试组/Leg 1-高温试验/数据表附件/工况记录.xlsx"
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
        ref = upload_existing_xlsx(root, LEG, "高温试验", src)
        assert ref.title == "工况记录表"
        dest = root / ref.relative_path
        assert dest.is_file()
        assert dest.parent == attachment_dir(root, LEG, "高温试验")
        assert dest.name == "工况记录表.xlsx"
        assert dest.read_bytes() == src.read_bytes()


def test_upload_same_name_gets_suffix_not_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = Path(tmp) / "outside" / "同名.xlsx"
        src.parent.mkdir()
        _write_bbox_fixture(src)
        first = upload_existing_xlsx(root, LEG, "高温试验", src)
        second = upload_existing_xlsx(root, LEG, "高温试验", src)
        assert first.title == "同名"
        assert second.title == "同名"
        assert first.relative_path != second.relative_path
        assert (root / first.relative_path).is_file()
        assert (root / second.relative_path).is_file()


def test_upload_then_preview_snapshot_keeps_bbox_empties():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = Path(tmp) / "outside" / "夹具.xlsx"
        src.parent.mkdir()
        _write_bbox_fixture(src)
        ref = upload_existing_xlsx(root, LEG, "高温试验", src)
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


def test_import_sample_ids_empty_col1_writes_from_row2():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty.xlsx"
        wb = Workbook()
        wb.save(path)
        wb.close()
        import_sample_ids(path, ["A01", "A02", "A03"])
        wb = load_workbook(path)
        ws = wb.active
        assert ws["A1"].value == "样品编号\nSample No."
        assert ws["A2"].value == "A01"
        assert ws["A3"].value == "A02"
        assert ws["A4"].value == "A03"
        wb.close()


def test_import_sample_ids_inserts_col_when_col1_has_content():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "filled.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "结果"
        ws["B1"] = "备注"
        wb.save(path)
        wb.close()
        import_sample_ids(path, ["S1", "S2"])
        wb = load_workbook(path)
        ws = wb.active
        assert ws["A1"].value == "样品编号\nSample No."
        assert ws["A2"].value == "S1"
        assert ws["A3"].value == "S2"
        assert ws["B1"].value == "结果"
        assert ws["C1"].value == "备注"
        wb.close()


def test_import_sample_ids_starts_below_multi_row_header():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "two_header.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.merge_cells("B1:D1")
        ws["B1"] = "试验后 after test"
        ws["B2"] = "桥路电阻"
        ws["C2"] = "短路电阻"
        ws["D2"] = "绝缘电阻"
        wb.save(path)
        wb.close()
        import_sample_ids(path, ["A01", "A02", "A03"])
        wb = load_workbook(path)
        ws = wb.active
        assert ws["A1"].value == "样品编号\nSample No."
        assert ws["A3"].value == "A01"
        assert ws["A4"].value == "A02"
        assert ws["A5"].value == "A03"
        assert ws["B1"].value == "试验后 after test"
        assert ws["B2"].value == "桥路电阻"
        wb.close()


def test_import_sample_ids_skips_header_when_already_present():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "labeled.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "样品编号 Sample No."
        ws.merge_cells("A1:A2")
        ws["B1"] = "值"
        wb.save(path)
        wb.close()
        import_sample_ids(path, ["X1"])
        wb = load_workbook(path)
        ws = wb.active
        assert ws["A1"].value == "样品编号 Sample No."
        assert ws["A3"].value == "X1"
        wb.close()


def test_infer_header_row_count_two_row_header_without_vertical_merge():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "two_header.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.merge_cells("B1:D1")
        ws["B1"] = "试验后 after test"
        ws["B2"] = "桥路电阻"
        ws["C2"] = "短路电阻"
        ws["D2"] = "绝缘电阻"
        ws["A3"] = "A22607480801-A01"
        wb.save(path)
        wb.close()
        snap = read_preview_snapshot(path)
        assert infer_header_row_count(snap) == 2


def test_infer_header_row_count_sample_no_label_with_merge_band():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "merge_header.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "样品编号 Sample No."
        ws.merge_cells("A1:A4")
        ws["B1"] = "试验前"
        ws["E1"] = "试验后"
        ws.merge_cells("B1:D1")
        ws.merge_cells("E1:G1")
        ws["B2"] = "Before test"
        ws["E2"] = "After test"
        ws.merge_cells("B2:D2")
        ws.merge_cells("E2:G2")
        ws["B3"] = "桥路电阻"
        ws["C3"] = "短路电阻"
        ws["D3"] = "绝缘电阻"
        ws["E3"] = "桥路电阻"
        ws["F3"] = "短路电阻"
        ws["G3"] = "绝缘电阻"
        ws["B4"] = "(Ω)"
        ws["C4"] = "(Ω)"
        ws["D4"] = "(MΩ)"
        ws["E4"] = "(Ω)"
        ws["F4"] = "(Ω)"
        ws["G4"] = "(MΩ)"
        ws["A5"] = "TP-1"
        wb.save(path)
        wb.close()
        snap = read_preview_snapshot(path)
        assert infer_header_row_count(snap) == 4


def test_import_sample_ids_missing_file_raises():
    try:
        import_sample_ids(Path("/tmp/no-such-data-table.xlsx"), ["A01"])
        raise AssertionError("expected DataTableError")
    except DataTableError:
        pass


def test_resolve_open_argv_prefers_excel_then_wps_then_default():
    excel = resolve_open_argv(
        Path("/tmp/a.xlsx"),
        platform="darwin",
        app_exists=lambda name: name == "Microsoft Excel",
    )
    assert excel == ["open", "-a", "Microsoft Excel", "/tmp/a.xlsx"]

    wps = resolve_open_argv(
        Path("/tmp/a.xlsx"),
        platform="darwin",
        app_exists=lambda name: name == "wpsoffice",
    )
    assert wps == ["open", "-a", "wpsoffice", "/tmp/a.xlsx"]

    fallback = resolve_open_argv(
        Path("/tmp/a.xlsx"),
        platform="darwin",
        app_exists=lambda _name: False,
    )
    assert fallback == ["open", "/tmp/a.xlsx"]


def test_open_attachment_uses_injected_runner_and_raises_on_failure():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "a.xlsx"
        wb = Workbook()
        wb.save(path)
        wb.close()

        calls = []

        def runner(argv, **_kwargs):
            calls.append(argv)

            class R:
                returncode = 0

            return R()

        open_attachment(
            path,
            runner=runner,
            resolve_argv=lambda p: ["open", "-a", "Microsoft Excel", str(p)],
        )
        assert calls == [["open", "-a", "Microsoft Excel", str(path)]]

        def fail_runner(_argv, **_kwargs):
            class R:
                returncode = 1
                stderr = "boom"

            return R()

        try:
            open_attachment(
                path,
                runner=fail_runner,
                resolve_argv=lambda p: ["open", str(p)],
            )
            raise AssertionError("expected DataTableError")
        except DataTableError as exc:
            assert "无法打开" in str(exc) or "打开" in str(exc)


def test_list_templates_empty_or_missing_is_safe():
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "nope"
        assert list_data_table_templates(missing) == []
        empty = Path(tmp) / "empty"
        empty.mkdir()
        assert list_data_table_templates(empty) == []


def test_copy_from_template_copies_and_titles_from_filename():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        root.mkdir()
        templates = Path(tmp) / "templates"
        templates.mkdir()
        src = templates / "高温记录.xlsx"
        _write_bbox_fixture(src)
        ref = copy_from_template(root, LEG, "高温试验", src)
        assert ref.title == "高温记录"
        dest = root / ref.relative_path
        assert dest.is_file()
        assert dest.parent == attachment_dir(root, LEG, "高温试验")
        assert dest.read_bytes() == src.read_bytes()


def test_list_templates_returns_xlsx_sorted_by_name():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "b.xlsx").write_bytes(b"PK")
        (folder / "a.xlsx").write_bytes(b"PK")
        (folder / "readme.txt").write_text("x")
        (folder / "skip").mkdir()
        names = [p.name for p in list_data_table_templates(folder)]
        assert names == ["a.xlsx", "b.xlsx"]


def test_delete_attachment_removes_file_missing_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ref = create_blank_workbook(root, LEG, "高温试验", "待删")
        path = root / ref.relative_path
        assert path.is_file()
        delete_attachment(path)
        assert not path.exists()
        delete_attachment(path)  # missing → no error


def test_rewrite_test_dir_in_relative_path():
    old_key = leg_test_dir_key(LEG, "湿热循环")
    new_key = leg_test_dir_key(LEG, "前湿热循环")
    assert (
        rewrite_test_dir_in_relative_path(
            f"3.测试组/{old_key}/数据表附件/工况.xlsx", old_key, new_key
        )
        == f"3.测试组/{new_key}/数据表附件/工况.xlsx"
    )
    assert (
        rewrite_test_dir_in_relative_path(
            "3.测试组/Leg 2-其他/数据表附件/a.xlsx", old_key, new_key
        )
        == "3.测试组/Leg 2-其他/数据表附件/a.xlsx"
    )


def test_retarget_node_data_tables():
    old_key = leg_test_dir_key(LEG, "湿热循环")
    new_key = leg_test_dir_key(LEG, "前湿热循环")
    node = TestNode(
        test_name="前湿热循环",
        data_tables=[
            DataTableRef(
                title="工况.xlsx",
                relative_path=f"3.测试组/{old_key}/数据表附件/工况.xlsx",
            )
        ],
    )
    retarget_node_data_tables(node, old_key, new_key)
    assert node.data_tables[0].relative_path == (
        f"3.测试组/{new_key}/数据表附件/工况.xlsx"
    )


def test_decimal_places_from_display_string():
    assert decimal_places("1.20") == 2
    assert decimal_places("1.2") == 1
    assert decimal_places("2") == 0
    assert decimal_places("-1.50") == 2
    assert decimal_places("") is None
    assert decimal_places("A01") is None
    assert decimal_places("1.2Ω") is None


def test_parse_numeric_display():
    assert parse_numeric_display("1.20") == 1.2
    assert parse_numeric_display("-3") == -3.0
    assert parse_numeric_display("样品") is None


def test_find_decimal_inconsistencies_flags_minority_in_column():
    snap = PreviewSnapshot(
        sheet_name="Sheet",
        values=[
            ["样品编号", "桥路", "短路"],
            ["A01", "1.20", "2.5"],
            ["A02", "1.2", "2.50"],
            ["A03", "1.21", "2.5"],
        ],
        merges=[],
    )
    # Header inferred as 1 (sample label in A1); col1 mode is 2 decimals → flag 1.2
    flagged = find_decimal_inconsistencies(snap)
    assert (2, 1) in flagged
    assert (1, 1) not in flagged
    assert (3, 1) not in flagged
    # col2 mode is 1 decimal → flag 2.50
    assert (2, 2) in flagged
    assert (1, 2) not in flagged


def test_find_decimal_inconsistencies_skips_sample_col_and_consistent():
    snap = PreviewSnapshot(
        sheet_name="Sheet",
        values=[
            ["样品编号", "值"],
            ["A01", "1.0"],
            ["A02", "2.0"],
        ],
        merges=[],
    )
    assert find_decimal_inconsistencies(snap) == []


def test_find_out_of_range_whole_table_and_column():
    snap = PreviewSnapshot(
        sheet_name="Sheet",
        values=[
            ["样品编号", "桥路", "短路"],
            ["A01", "1.2", "9.0"],
            ["A02", "5.0", "2.5"],
        ],
        merges=[],
    )
    all_hit = find_out_of_range(snap, 0.0, 3.0)
    assert set(all_hit) == {(1, 2), (2, 1)}
    col_hit = find_out_of_range(snap, 0.0, 3.0, col=1)
    assert col_hit == [(2, 1)]
    assert find_out_of_range(snap, 0.0, 3.0, col=0) == []


def test_find_bound_row_indices_zh_en_bilingual_and_old_label():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "电流"],
            ["上限", "5"],
            ["下限", "1"],
            ["A01", "3"],
        ],
        merges=[],
    )
    bound = find_bound_row_indices(snap)
    assert bound.upper == 1
    assert bound.lower == 2
    assert has_limit_row(snap) is True

    en = PreviewSnapshot(
        sheet_name="S",
        values=[["Sample No.", "I"], ["Upper", "5"], ["Lower", "1"], ["A01", "3"]],
        merges=[],
    )
    en_b = find_bound_row_indices(en)
    assert en_b.upper == 1 and en_b.lower == 2

    bilingual = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "电流"],
            ["上限\nUpper", "5"],
            ["下限 / Lower", "1"],
        ],
        merges=[],
    )
    bi = find_bound_row_indices(bilingual)
    assert bi.upper == 1 and bi.lower == 2

    reversed_order = PreviewSnapshot(
        sheet_name="S",
        values=[["样品编号", "电流"], ["下限", "1"], ["上限", "5"], ["A01", "3"]],
        merges=[],
    )
    rev = find_bound_row_indices(reversed_order)
    assert rev.lower == 1 and rev.upper == 2

    old = PreviewSnapshot(
        sheet_name="S",
        values=[["样品编号", "桥路"], ["限值", "0～3"], ["A01", "1"]],
        merges=[],
    )
    assert find_bound_row_indices(old).indices() == ()
    assert has_limit_row(old) is False

    data_label = PreviewSnapshot(
        sheet_name="S",
        values=[["样品编号", ""], ["数据上限", "5"], ["数据下限", "1"]],
        merges=[],
    )
    dl = find_bound_row_indices(data_label)
    assert dl.upper == 1 and dl.lower == 2

    side = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "", "9V"],
            ["", "上限", "5"],
            ["", "下限", "1"],
            ["A01", "", "3"],
        ],
        merges=[],
    )
    sb = find_bound_row_indices(side)
    assert sb.upper == 1 and sb.lower == 2 and sb.label_col == 1
    assert find_out_of_range_by_limits(side, inclusive=True) == []

    empty = PreviewSnapshot(
        sheet_name="S", values=[["样品编号", "桥路"], ["A01", "1"]], merges=[]
    )
    assert has_limit_row(empty) is False


def test_value_violates_limit_inclusive_and_exclusive():
    closed = LimitRule(lo=1.0, hi=5.0)
    assert value_violates_limit(1.0, closed) is False
    assert value_violates_limit(5.0, closed) is False
    assert value_violates_limit(0.9, closed) is True
    assert value_violates_limit(5.1, closed) is True

    opened = LimitRule(lo=1.0, hi=5.0, lo_exclusive=True, hi_exclusive=True)
    assert value_violates_limit(1.0, opened) is True
    assert value_violates_limit(5.0, opened) is True
    assert value_violates_limit(1.1, opened) is False
    assert value_violates_limit(4.9, opened) is False

    upper_only = LimitRule(hi=5.0)
    assert value_violates_limit(5.0, upper_only) is False
    assert value_violates_limit(5.1, upper_only) is True
    upper_open = LimitRule(hi=5.0, hi_exclusive=True)
    assert value_violates_limit(5.0, upper_open) is True

    lower_only = LimitRule(lo=1.0)
    assert value_violates_limit(1.0, lower_only) is False
    lower_open = LimitRule(lo=1.0, lo_exclusive=True)
    assert value_violates_limit(1.0, lower_open) is True

    zero = LimitRule(lo=0.0)
    assert value_violates_limit(-0.1, zero) is True
    assert value_violates_limit(0.0, zero) is False


def test_find_out_of_range_split_columns_do_not_form_interval():
    """图1：上限在电流、下限在电阻 → 分列判定，不打包成 1～5。"""
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "电流", "电阻"],
            ["上限", "5", ""],
            ["下限", "", "1"],
            ["A01", "5", "1"],
            ["A02", "6", "0"],
            ["A03", "3", "2"],
        ],
        merges=[],
    )
    # inclusive: 电流 ≤5, 电阻 ≥1
    flagged = find_out_of_range_by_limits(snap, inclusive=True)
    assert set(flagged) == {(4, 1), (4, 2)}
    opened = find_out_of_range_by_limits(snap, inclusive=False)
    assert set(opened) == {(3, 1), (3, 2), (4, 1), (4, 2)}


def test_find_out_of_range_same_column_applies_whole_table():
    """图2：上下限都在电流列 → 整表按 1～5。"""
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "电流", "电阻"],
            ["上限", "5", ""],
            ["下限", "1", ""],
            ["A01", "3", "3"],
            ["A02", "5", "1"],
            ["A03", "6", "0"],
        ],
        merges=[],
    )
    flagged = find_out_of_range_by_limits(snap, inclusive=True)
    assert set(flagged) == {(5, 1), (5, 2)}
    opened = find_out_of_range_by_limits(snap, inclusive=False)
    assert set(opened) == {(4, 1), (4, 2), (5, 1), (5, 2)}


def test_find_out_of_range_by_limits_per_column_and_skips():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "桥路", "短路", "备注"],
            ["上限", "3", "100", ""],
            ["下限", "0", "0", ""],
            ["A01", "1.2", "9.0", "ok"],
            ["A02", "5.0", "2.5", "x"],
            ["A03", "2.0", "1.0", ""],
        ],
        merges=[],
    )
    flagged = find_out_of_range_by_limits(snap)
    assert set(flagged) == {(4, 1)}
    assert (1, 1) not in flagged
    assert (2, 1) not in flagged
    assert (3, 2) not in flagged


def test_find_out_of_range_by_limits_no_bound_rows_returns_empty():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[["样品编号", "值"], ["A01", "9"]],
        merges=[],
    )
    assert find_out_of_range_by_limits(snap) == []


def test_find_out_of_range_by_limits_bound_rows_but_no_numbers_passes():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[["样品编号", "值"], ["上限", ""], ["下限", ""], ["A01", "9"]],
        merges=[],
    )
    assert has_limit_row(snap)
    assert find_out_of_range_by_limits(snap) == []


def test_find_out_of_range_only_upper_row():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[["样品编号", "值"], ["上限", "5"], ["A01", "5"], ["A02", "6"]],
        merges=[],
    )
    assert find_out_of_range_by_limits(snap, inclusive=True) == [(3, 1)]
    assert set(find_out_of_range_by_limits(snap, inclusive=False)) == {(2, 1), (3, 1)}


def test_import_sample_ids_preserves_bound_rows():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "with_limit.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["B1"] = "-40°C"
        ws["B2"] = "9V"
        ws["A3"] = "上限"
        ws["B3"] = "10"
        ws["A4"] = "下限"
        ws["B4"] = "0"
        wb.save(path)
        wb.close()
        import_sample_ids(path, ["A01", "A02"])
        wb = load_workbook(path)
        ws = wb.active
        assert "样品编号" in str(ws["A1"].value or "")
        assert ws["A3"].value in (None, "样品编号\nSample No.")
        assert ws["B3"].value == "上限"
        assert ws["B4"].value == "下限"
        assert ws["C3"].value == 10 or str(ws["C3"].value) == "10"
        assert ws["C4"].value == 0 or str(ws["C4"].value) == "0"
        assert ws["A5"].value == "A01"
        assert ws["A6"].value == "A02"
        merges = {str(rng) for rng in ws.merged_cells.ranges}
        assert any(m.startswith("A1:") and m.endswith("A4") for m in merges)
        assert "A5:B5" in merges
        assert "A6:B6" in merges
        assert ws["A5"].alignment.horizontal == "center"
        assert ws["A1"].alignment.vertical == "center"
        wb.close()


def test_import_sample_ids_bound_labels_already_in_col_b():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "already.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "样品编号\nSample No."
        ws.merge_cells("A1:A4")
        ws["C1"] = "-40°C"
        ws["C2"] = "9V"
        ws["B3"] = "上限"
        ws["B4"] = "下限"
        ws["A5"] = "OLD"
        wb.save(path)
        wb.close()
        import_sample_ids(path, ["A01"])
        wb = load_workbook(path)
        ws = wb.active
        assert ws["B3"].value == "上限"
        assert ws["C1"].value == "-40°C"
        assert ws["A5"].value == "A01"
        assert "A5:B5" in {str(rng) for rng in ws.merged_cells.ranges}
        wb.close()


def test_import_sample_ids_fills_empty_bound_cells_with_slash():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "limits.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["B1"] = "9V"
        ws["C1"] = "14V"
        ws["D1"] = "16V"
        ws["A2"] = "数据上限"
        ws["B2"] = 5
        ws["C2"] = 2
        ws["A3"] = "数据下限"
        ws["B3"] = 1
        ws["C3"] = 1
        wb.save(path)
        wb.close()
        import_sample_ids(path, ["A01"])
        wb = load_workbook(path)
        ws = wb.active
        assert ws["B2"].value == "数据上限"
        assert ws["C2"].value == 5 or str(ws["C2"].value) == "5"
        assert ws["D2"].value == 2 or str(ws["D2"].value) == "2"
        assert ws["E2"].value == "/"
        assert ws["E3"].value == "/"
        assert ws["A4"].value == "A01"
        wb.close()


def test_sync_display_layout_fills_slash_and_merges_existing_ids():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "existing.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "样品编号Sample No."
        ws["C1"] = "9V"
        ws["D1"] = "14V"
        ws["E1"] = "16V"
        ws["B2"] = "数据上限"
        ws["C2"] = 5
        ws["D2"] = 2
        ws["B3"] = "数据下限"
        ws["C3"] = 1
        ws["D3"] = 1
        ws["A4"] = "A22600280175-A01"
        ws["C4"] = 1
        ws["A5"] = "A22600280175-A02"
        ws["C5"] = 2
        wb.save(path)
        wb.close()
        sync_display_layout(path)
        wb = load_workbook(path)
        ws = wb.active
        assert "样品编号" in str(ws["A1"].value or "")
        assert ws["A4"].value == "A22600280175-A01"
        assert ws["A5"].value == "A22600280175-A02"
        assert ws["E2"].value == "/"
        assert ws["E3"].value == "/"
        assert ws["C2"].value == 5 or str(ws["C2"].value) == "5"
        merges = {str(rng) for rng in ws.merged_cells.ranges}
        assert any(m.startswith("A1:") and m.endswith("A3") for m in merges)
        assert "A4:B4" in merges
        assert "A5:B5" in merges
        wb.close()


def test_sync_display_layout_skips_sheets_without_bound_rows():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "plain.xlsx"
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "样品编号"
        ws["B1"] = "值"
        ws["A2"] = "A01"
        ws["B2"] = 9
        wb.save(path)
        wb.close()
        sync_display_layout(path)
        wb = load_workbook(path)
        ws = wb.active
        assert ws["A2"].value == "A01"
        assert ws["B2"].value == 9 or str(ws["B2"].value) == "9"
        assert list(ws.merged_cells.ranges) == []
        wb.close()


def test_prepare_display_snapshot_drops_bound_rows_when_excluded():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "桥路"],
            ["上限", "3"],
            ["下限", "0"],
            ["A01", "1.0"],
        ],
        merges=[],
        origin_row=1,
        origin_col=1,
    )
    out = prepare_display_snapshot(snap, include_limit_row=False)
    assert len(out.values) == 2
    assert out.values[0][0] == "样品编号"
    assert out.values[1][0] == "A01"
    assert "上限" not in {r[0] for r in out.values}
    assert "下限" not in {r[0] for r in out.values}


def test_prepare_display_snapshot_single_occupied_spans_data_cols():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "电流", "电阻"],
            ["上限", "5", ""],
            ["下限", "1", ""],
            ["A01", "3", "3"],
        ],
        merges=[],
        origin_row=1,
        origin_col=1,
    )
    out = prepare_display_snapshot(snap, include_limit_row=True)
    assert out.values[1][0] == "上限"
    assert out.values[1][1] == "5"
    assert out.values[1][2] == ""
    assert out.values[2][0] == "下限"
    assert out.values[2][1] == "1"
    assert out.values[2][2] == ""
    assert any(m.startswith("B2:") for m in out.merges)
    assert any(m.startswith("B3:") for m in out.merges)


def test_prepare_display_snapshot_split_columns_fill_slash():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "电流", "电阻"],
            ["上限", "5", ""],
            ["下限", "", "1"],
            ["A01", "3", "3"],
        ],
        merges=[],
        origin_row=1,
        origin_col=1,
    )
    out = prepare_display_snapshot(snap, include_limit_row=True)
    assert out.values[1] == ["上限", "5", "/"]
    assert out.values[2] == ["下限", "/", "1"]


def test_find_decimal_inconsistencies_skips_bound_rows():
    snap = PreviewSnapshot(
        sheet_name="S",
        values=[
            ["样品编号", "值"],
            ["上限", "5"],
            ["下限", "1.0"],
            ["A01", "5.0"],
            ["A02", "5.0"],
        ],
        merges=[],
    )
    assert find_decimal_inconsistencies(snap) == []


def _five_point_snapshot(*, copies: int = 1) -> PreviewSnapshot:
    """Build a 5-point-style header: sample + N×(-40/25/85 × 9/14/16V)."""
    temps = ["-40°C", "25°C", "85°C"] * copies
    volts = ["9V", "14V", "16V"]
    row0 = ["样品编号 / Sample No."]
    row1 = [""]
    merges: list[str] = []
    col = 1
    for temp in temps:
        row0.append(temp)
        row0.extend(["", ""])
        row1.extend(volts)
        start = get_column_letter(col + 1)
        end = get_column_letter(col + 3)
        merges.append(f"{start}1:{end}1")
        col += 3
    merges.append("A1:A2")
    values = [
        row0,
        row1,
        ["A01"] + ["1"] * (len(row0) - 1),
        ["A02"] + ["2"] * (len(row0) - 1),
    ]
    return PreviewSnapshot(sheet_name="S", values=values, merges=merges)


def test_content_column_groups_keeps_temperature_blocks():
    snap = _five_point_snapshot(copies=1)
    groups = content_column_groups(snap)
    assert groups == [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


def test_split_preview_snapshot_repeats_sample_and_keeps_merges():
    snap = _five_point_snapshot(copies=2)  # 18 content cols
    assert max(len(r) for r in snap.values) == 19
    chunks = split_preview_snapshot_for_page(snap, max_content_cols=12)
    assert len(chunks) == 2
    assert max(len(r) for r in chunks[0].values) == 13  # sample + 12
    assert max(len(r) for r in chunks[1].values) == 7  # sample + 6
    for chunk in chunks:
        assert chunk.values[0][0].startswith("样品编号")
        assert chunk.values[2][0] == "A01"
        groups = content_column_groups(chunk)
        assert all(len(g) == 3 for g in groups)


def test_slice_preview_snapshot_remaps_merges():
    snap = _five_point_snapshot(copies=1)
    sliced = slice_preview_snapshot(snap, [0, 7, 8, 9])  # sample + 85°C block
    assert sliced.values[0][1] == "85°C"
    assert "B1:D1" in sliced.merges
    assert "A1:A2" in sliced.merges


if __name__ == "__main__":
    test_create_blank_workbook_writes_xlsx_and_returns_ref()
    test_create_blank_rejects_unusable_test_name()
    test_create_blank_unique_filename_does_not_overwrite()
    test_list_attachment_refs_scans_sorted_by_filename_skips_temp()
    test_list_attachment_refs_empty_or_missing_folder()
    test_list_attachment_refs_picks_up_manually_dropped_file()
    test_data_table_index_round_trips_in_project_json()
    test_upload_copies_xlsx_and_titles_from_filename()
    test_upload_same_name_gets_suffix_not_overwrite()
    test_upload_then_preview_snapshot_keeps_bbox_empties()
    test_preview_snapshot_is_bbox_keeps_empty_cells_and_merges()
    test_preview_refresh_rereads_disk_changes()
    test_import_sample_ids_empty_col1_writes_from_row2()
    test_import_sample_ids_inserts_col_when_col1_has_content()
    test_import_sample_ids_starts_below_multi_row_header()
    test_import_sample_ids_missing_file_raises()
    test_find_bound_row_indices_zh_en_bilingual_and_old_label()
    test_value_violates_limit_inclusive_and_exclusive()
    test_find_out_of_range_split_columns_do_not_form_interval()
    test_find_out_of_range_same_column_applies_whole_table()
    test_find_out_of_range_by_limits_per_column_and_skips()
    test_find_out_of_range_by_limits_no_bound_rows_returns_empty()
    test_find_out_of_range_by_limits_bound_rows_but_no_numbers_passes()
    test_find_out_of_range_only_upper_row()
    test_import_sample_ids_preserves_bound_rows()
    test_import_sample_ids_bound_labels_already_in_col_b()
    test_import_sample_ids_fills_empty_bound_cells_with_slash()
    test_sync_display_layout_fills_slash_and_merges_existing_ids()
    test_sync_display_layout_skips_sheets_without_bound_rows()
    test_prepare_display_snapshot_drops_bound_rows_when_excluded()
    test_prepare_display_snapshot_single_occupied_spans_data_cols()
    test_prepare_display_snapshot_split_columns_fill_slash()
    test_find_decimal_inconsistencies_skips_bound_rows()
    test_resolve_open_argv_prefers_excel_then_wps_then_default()
    test_open_attachment_uses_injected_runner_and_raises_on_failure()
    test_list_templates_empty_or_missing_is_safe()
    test_copy_from_template_copies_and_titles_from_filename()
    test_list_templates_returns_xlsx_sorted_by_name()
    test_delete_attachment_removes_file_missing_is_noop()
    test_retarget_node_data_tables()
    test_content_column_groups_keeps_temperature_blocks()
    test_split_preview_snapshot_repeats_sample_and_keeps_merges()
    test_slice_preview_snapshot_remaps_merges()
    print("test_data_tables: ok")