from datetime import date
from pathlib import Path
from unittest.mock import patch
import json

from src.io.project_board import (
    BOARD_COLUMNS,
    board_progress_ratio,
    filter_board_rows,
    find_project_intranet_dir,
    group_board_rows,
    highlight_html,
    highlight_spans,
    list_board_rows,
    locate_project_intranet_folder,
    open_folder_in_file_manager,
    project_intranet_year_root,
    resolve_intranet_year_root,
    update_board_sample_qty,
    update_board_test_sample_qty,
)
from src.models.project_state import (
    ProjectState,
    TestEquipment,
    TestLeg,
    TestNode,
    TestSample,
    TestStandard,
)


TODAY = date(2026, 9, 1)


def _save(root: Path, state: ProjectState) -> None:
    pid = state.project_id
    path = root / pid / "project_state.json"
    state.save_to_file(str(path))


def _incomplete_node(name: str, start: str, end: str, **kwargs) -> TestNode:
    return TestNode(test_name=name, start_date=start, end_date=end, **kwargs)


def _complete_node(name: str, start: str, end: str) -> TestNode:
    return TestNode(
        test_name=name,
        start_date=start,
        end_date=end,
        standard_id="GB/T 1",
        standard_chapter="1",
        standard_test_name=name,
        standards=[
            TestStandard(standard_id="GB/T 1", chapter="1", test_name=name)
        ],
        equipments=[TestEquipment(name="温箱", code="H001")],
        samples=[TestSample(sample_id="A01")],
    )


def test_intranet_year_root_appends_year_folder():
    assert (
        project_intranet_year_root(2026)
        == "smb://10.10.31.8/材料实验室b/车载电子/2026年"
    )
    assert project_intranet_year_root(2027, share="smb://lab/ee/") == "smb://lab/ee/2027年"
    assert project_intranet_year_root(2026, share="") == ""
    with patch("src.io.network_sources.sys.platform", "darwin"):
        assert resolve_intranet_year_root(2026) == Path("/Volumes/材料实验室b/车载电子/2026年")
    with patch("src.io.network_sources.sys.platform", "win32"):
        from src.io.network_sources import normalize_config_path

        assert normalize_config_path(project_intranet_year_root(2026)) == (
            "\\\\10.10.31.8\\材料实验室b\\车载电子\\2026年"
        )


def test_find_project_intranet_dir_under_month(tmp_path):
    month = tmp_path / "8月"
    month.mkdir()
    target = month / "A2260715291101方向盘总成"
    target.mkdir()
    (month / "A2260688978101左安全气帘总成").mkdir()
    found = find_project_intranet_dir("A2260715291101", 2026, year_root=tmp_path)
    assert found == target


def test_find_project_intranet_dir_exact_name_wins(tmp_path):
    month = tmp_path / "8月"
    month.mkdir()
    exact = month / "A2260715291101"
    extra = month / "A2260715291101方向盘总成"
    extra.mkdir()
    exact.mkdir()
    found = find_project_intranet_dir("A2260715291101", 2026, year_root=tmp_path)
    assert found == exact


def test_find_project_intranet_dir_missing_or_empty(tmp_path):
    (tmp_path / "8月").mkdir()
    assert find_project_intranet_dir("A2260715291101", 2026, year_root=tmp_path) is None
    assert find_project_intranet_dir("", 2026, year_root=tmp_path) is None
    assert find_project_intranet_dir("A2260715291101", 2026, year_root=tmp_path / "nope") is None


def test_find_project_intranet_dir_at_year_root(tmp_path):
    target = tmp_path / "A2260715291101"
    target.mkdir()
    assert find_project_intranet_dir("A2260715291101", 2026, year_root=tmp_path) == target


def test_find_project_intranet_dir_skips_files(tmp_path):
    month = tmp_path / "8月"
    month.mkdir()
    (month / "A2260715291101.txt").write_text("not a folder", encoding="utf-8")
    target = month / "A2260715291101方向盘总成"
    target.mkdir()
    assert find_project_intranet_dir("A2260715291101", 2026, year_root=tmp_path) == target


def test_find_project_intranet_dir_exact_in_early_month_wins(tmp_path):
    first = tmp_path / "1月" / "A2260715291101"
    later = tmp_path / "12月" / "A2260715291101方向盘总成"
    first.mkdir(parents=True)
    later.mkdir(parents=True)
    assert find_project_intranet_dir("A2260715291101", 2026, year_root=tmp_path) == first


def test_locate_project_intranet_folder_statuses(tmp_path):
    missing_root = tmp_path / "nope"
    assert locate_project_intranet_folder("A1", 2026, year_root=missing_root).status == "not_ready"
    (tmp_path / "8月").mkdir()
    assert locate_project_intranet_folder("A1", 2026, year_root=tmp_path).status == "missing"
    target = tmp_path / "8月" / "A1样品"
    target.mkdir()
    result = locate_project_intranet_folder("A1", 2026, year_root=tmp_path)
    assert result.status == "found"
    assert result.path == target


def test_open_folder_in_file_manager_uses_explorer_on_windows(tmp_path):
    launched = []
    target = tmp_path / "A1"
    target.mkdir()
    open_folder_in_file_manager(
        target,
        platform="win32",
        popen=lambda args, **kwargs: launched.append((args, kwargs)),
    )
    assert launched[0][0] == ["explorer", str(target)]
    assert launched[0][1].get("close_fds") is False


def test_open_folder_in_file_manager_uses_open_on_macos(tmp_path):
    launched = []
    target = tmp_path / "A1"
    target.mkdir()
    open_folder_in_file_manager(
        target,
        platform="darwin",
        popen=lambda args, **kwargs: launched.append(args),
    )
    assert launched == [["open", str(target)]]


def test_highlight_spans_are_case_insensitive():
    assert highlight_spans("Q/JLY J7110520C-2021 / 8.3.4", "j711") == [(6, 10)]
    assert highlight_spans("环境交变试验", "交变") == [(2, 4)]
    assert highlight_spans("耐寒性能", "") == []
    assert "j711" in highlight_html("Q/JLY J7110520C-2021", "J711").lower()
    assert "background-color" in highlight_html("Q/JLY J7110520C-2021", "J711")


def test_board_columns_hide_applicant_and_keep_status_notes():
    assert "委托方" not in BOARD_COLUMNS
    assert "试验员" not in BOARD_COLUMNS
    assert "项目状态" in BOARD_COLUMNS
    assert "标准" in BOARD_COLUMNS
    assert "TO号" in BOARD_COLUMNS
    assert "备注" in BOARD_COLUMNS


def test_progress_ratio_clamps_to_schedule():
    start = date(2026, 8, 1)
    end = date(2026, 8, 31)
    assert board_progress_ratio(start, end, date(2026, 7, 15)) == 0.0
    assert board_progress_ratio(start, end, date(2026, 8, 16)) == 0.5
    assert board_progress_ratio(start, end, date(2026, 9, 1)) == 1.0
    assert board_progress_ratio(None, end, TODAY) is None


def test_list_board_rows_one_row_per_test_card(tmp_path):
    state = ProjectState(
        project_id="A22600000001",
        applicant_name="均胜",
        sample_name="主气囊",
        tester_name="黄佳林",
        test_start_date="2026-06-05",
        test_end_date="2026-07-02",
        application_fields={"送样数量": "3", "申请公司": "均胜"},
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    _incomplete_node("温度循环试验", "2026-06-05", "2026-06-20"),
                    _incomplete_node("振动试验", "2026-06-21", "2026-07-02"),
                ],
            )
        ],
    )
    _save(tmp_path, state)

    rows = list_board_rows(tmp_path, today=TODAY)
    assert [row.test_name for row in rows] == ["温度循环试验", "振动试验"]
    assert {row.project_id for row in rows} == {"A22600000001"}
    assert rows[0].sample_name == "主气囊"
    assert rows[0].sample_qty == ""
    assert rows[0].project_sample_qty == "3"
    assert rows[0].applicant == "均胜"
    assert rows[0].start == date(2026, 6, 5)
    assert rows[0].end == date(2026, 6, 20)
    assert rows[1].start == date(2026, 6, 21)
    assert rows[0].tester_name == "黄佳林"
    assert rows[0].progress == 1.0
    assert rows[1].progress == 1.0

    groups = group_board_rows(rows, today=TODAY)
    assert len(groups) == 1
    assert groups[0].project_id == "A22600000001"
    assert groups[0].sample_qty == "3"
    assert [row.test_name for row in groups[0].tests] == ["温度循环试验", "振动试验"]
    assert groups[0].start == date(2026, 6, 5)
    assert groups[0].end == date(2026, 7, 2)
    assert groups[0].progress == 1.0


def test_board_shows_standards_and_selected_to(tmp_path):
    state = ProjectState(
        project_id="A22606909401",
        applicant_name="奥托立夫（上海）汽车安全系统研发有限公司",
        sample_name="司机气囊",
        to_numbers=["TO-26112398-04", "TO-26112398-05", "TO-26112398-06"],
        to_numbers_display="TO-26112398-04/05/06",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(
                        test_name="湿热老化",
                        start_date="2026-08-11",
                        end_date="2026-08-28",
                        selected_to="TO-26112398-04",
                        standards=[
                            TestStandard(
                                standard_id="VW 825 11",
                                chapter="8.3.4",
                                test_name="湿热老化",
                            )
                        ],
                    ),
                    _incomplete_node("高温老化", "2026-08-11", "2026-09-10"),
                ],
            )
        ],
    )
    _save(tmp_path, state)
    rows = list_board_rows(tmp_path, today=TODAY)
    assert len(rows) == 2
    assert rows[0].to_number == "TO-26112398-04"
    assert rows[0].standards_text == "VW 825 11 / 8.3.4"
    assert "湿热老化" not in rows[0].standards_text
    assert rows[1].to_number == "TO-26112398-04/05/06"
    assert rows[1].standards_text == ""


def test_empty_project_still_one_row(tmp_path):
    _save(tmp_path, ProjectState(project_id="TEST001", sample_name=""))
    rows = list_board_rows(tmp_path, today=TODAY)
    assert len(rows) == 1
    assert rows[0].project_id == "TEST001"
    assert rows[0].test_name == ""
    assert rows[0].progress is None


def test_overdue_incomplete_test_is_flagged(tmp_path):
    state = ProjectState(
        project_id="A22600000003",
        sample_name="侧气囊",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    _incomplete_node("高温试验", "2026-08-01", "2026-08-20"),
                    _incomplete_node("低温试验", "2026-09-10", "2026-09-20"),
                ],
            )
        ],
    )
    _save(tmp_path, state)
    rows = list_board_rows(tmp_path, today=TODAY)
    by_name = {row.test_name: row for row in rows}
    assert by_name["高温试验"].overdue is True
    assert by_name["低温试验"].overdue is False


def test_completed_past_test_is_not_overdue(tmp_path):
    state = ProjectState(
        project_id="A22600000004",
        sample_name="已完成件",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[_complete_node("温度循环试验", "2026-06-01", "2026-06-15")],
            )
        ],
    )
    _save(tmp_path, state)
    row = list_board_rows(tmp_path, today=TODAY)[0]
    assert row.overdue is False


def test_filter_board_rows_matches_project_and_test_name(tmp_path):
    _save(
        tmp_path,
        ProjectState(
            project_id="A22605082131",
            applicant_name="均胜",
            sample_name="主气囊",
            tester_name="黄佳林",
            legs=[
                TestLeg(
                    leg_id="L1",
                    leg_name="Leg 1",
                    nodes=[_incomplete_node("自由跌落试验", "2026-08-01", "2026-09-15")],
                )
            ],
        ),
    )
    _save(
        tmp_path,
        ProjectState(
            project_id="A22602199091",
            applicant_name="别的客户",
            sample_name="控制器",
            tester_name="孔",
            legs=[
                TestLeg(
                    leg_id="L1",
                    leg_name="Leg 1",
                    nodes=[_incomplete_node("振动试验", "2026-06-01", "2026-07-01")],
                )
            ],
        ),
    )
    rows = list_board_rows(tmp_path, today=TODAY)
    assert len(filter_board_rows(rows, "")) == 2
    hit = filter_board_rows(rows, "自由跌落")
    assert [row.project_id for row in hit] == ["A22605082131"]
    hit = filter_board_rows(rows, "均胜")
    assert [row.project_id for row in hit] == ["A22605082131"]
    hit = filter_board_rows(rows, "a22602199091")
    assert [row.project_id for row in hit] == ["A22602199091"]


def test_group_board_rows_aggregates_span_and_keeps_projects_apart(tmp_path):
    _save(
        tmp_path,
        ProjectState(
            project_id="A2260715291101",
            sample_name="方向盘总成",
            tester_name="展玮鸿",
            legs=[
                TestLeg(
                    leg_id="L1",
                    leg_name="Leg 1",
                    nodes=[
                        _incomplete_node("环境交变试验", "2026-08-18", "2026-08-28"),
                        _incomplete_node("耐寒性能", "2026-08-18", "2026-09-07"),
                    ],
                )
            ],
        ),
    )
    _save(
        tmp_path,
        ProjectState(
            project_id="A2260688978101",
            sample_name="左安全气帘",
            tester_name="展玮鸿",
            legs=[
                TestLeg(
                    leg_id="L1",
                    leg_name="Leg 1",
                    nodes=[_incomplete_node("振动试验", "2026-08-01", "2026-09-10")],
                )
            ],
        ),
    )
    rows = list_board_rows(tmp_path, today=TODAY)
    groups = group_board_rows(rows, today=TODAY)
    by_id = {group.project_id: group for group in groups}
    folded = by_id["A2260715291101"]
    assert len(folded.tests) == 2
    assert folded.start == date(2026, 8, 18)
    assert folded.end == date(2026, 9, 7)
    assert folded.progress == board_progress_ratio(
        date(2026, 8, 18), date(2026, 9, 7), TODAY
    )
    assert len(by_id["A2260688978101"].tests) == 1


def test_skips_corrupt_and_folder_without_json(tmp_path):
    empty = tmp_path / "NOJSON"
    empty.mkdir()
    bad = tmp_path / "BADJSON"
    bad.mkdir()
    (bad / "project_state.json").write_text("{not-json", encoding="utf-8")
    _save(
        tmp_path,
        ProjectState(project_id="A22600000005", sample_name="ok"),
    )
    rows = list_board_rows(tmp_path, today=TODAY)
    assert [row.project_id for row in rows] == ["A22600000005"]


def test_qty_falls_back_to_customer_quantity_key(tmp_path):
    state = ProjectState(
        project_id="A22600000006",
        sample_name="执行器",
        application_fields={"客户送样数量": "6"},
    )
    _save(tmp_path, state)
    row = list_board_rows(tmp_path, today=TODAY)[0]
    assert row.project_sample_qty == "6"
    assert row.sample_qty == ""
    assert group_board_rows([row], today=TODAY)[0].sample_qty == "6"


def test_update_board_sample_qty_persists_and_rereads(tmp_path):
    state = ProjectState(
        project_id="A22600000007",
        sample_name="控制器",
        application_fields={"送样数量": "3", "样品名称": "控制器"},
        application_columns=[{"送样数量": "3", "样品名称": "控制器"}],
        active_sample_column_index=0,
    )
    _save(tmp_path, state)
    path = tmp_path / "A22600000007" / "project_state.json"
    assert update_board_sample_qty(path, "3+3+3") is True
    row = list_board_rows(tmp_path, today=TODAY)[0]
    assert row.project_sample_qty == "3+3+3"
    assert row.sample_qty == ""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["application_fields"]["送样数量"] == "3+3+3"
    assert data["application_columns"][0]["送样数量"] == "3+3+3"


def test_update_board_sample_qty_clear_removes_fallback_key(tmp_path):
    state = ProjectState(
        project_id="A22600000008",
        application_fields={"客户送样数量": "6"},
    )
    _save(tmp_path, state)
    path = tmp_path / "A22600000008" / "project_state.json"
    assert update_board_sample_qty(path, "") is True
    row = list_board_rows(tmp_path, today=TODAY)[0]
    assert row.project_sample_qty == ""
    assert row.sample_qty == ""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "客户送样数量" not in data["application_fields"]
    assert "送样数量" not in data["application_fields"]


def test_update_board_test_sample_qty_persists_independently(tmp_path):
    state = ProjectState(
        project_id="A22600000009",
        sample_name="气囊",
        application_fields={"送样数量": "3"},
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    _incomplete_node("高温试验", "2026-08-01", "2026-08-20"),
                    _incomplete_node("振动试验", "2026-08-21", "2026-08-30"),
                ],
            )
        ],
    )
    _save(tmp_path, state)
    path = tmp_path / "A22600000009" / "project_state.json"
    assert update_board_test_sample_qty(path, 0, 1, "2+2") is True
    rows = list_board_rows(tmp_path, today=TODAY)
    assert rows[0].sample_qty == ""
    assert rows[0].project_sample_qty == "3"
    assert rows[1].sample_qty == "2+2"
    assert rows[1].project_sample_qty == "3"
    group = group_board_rows(rows, today=TODAY)[0]
    assert group.sample_qty == "3"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["application_fields"]["送样数量"] == "3"
    assert data["legs"][0]["nodes"][1]["sample_qty"] == "2+2"
    assert not str(data["legs"][0]["nodes"][0].get("sample_qty") or "").strip()


def test_overview_shows_compact_to_numbers():
    state = ProjectState(
        project_id="A1",
        applicant_name="奥托立夫（上海）汽车安全系统研发有限公司",
        to_numbers=["TO-1234-01", "TO-1234-02", "TO-1234-03"],
        to_numbers_display="TO-1234-01/02/03",
        application_fields={"申请单号": "A1"},
    )
    rows = dict(state.iter_overview_fields())
    assert rows["TO号"] == "TO-1234-01/02/03"
