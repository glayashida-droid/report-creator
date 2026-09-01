from datetime import date
from pathlib import Path

from src.io.project_board import (
    BOARD_COLUMNS,
    board_progress_ratio,
    filter_board_rows,
    group_board_rows,
    highlight_html,
    highlight_spans,
    list_board_rows,
    project_intranet_url,
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


def test_intranet_url_waits_for_base():
    assert project_intranet_url("A2260715291101") == ""
    assert project_intranet_url("A2260715291101", base="") == ""
    assert (
        project_intranet_url("A2260715291101", base="smb://lab/projects/")
        == "smb://lab/projects/A2260715291101"
    )


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
    assert rows[0].sample_qty == "3"
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
    assert row.sample_qty == "6"


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
