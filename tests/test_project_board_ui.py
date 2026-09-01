import sys
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLineEdit,
    QProgressBar,
    QWidget,
)

from src.io.project_board import BOARD_COLUMNS
from src.models.project_state import (
    ProjectState,
    TestEquipment,
    TestLeg,
    TestNode,
    TestSample,
    TestStandard,
)
from src.ui.board_gate_dialog import BoardGateDialog
from src.ui.main_window import MainWindow
from src.ui.project_board import (
    COL_END,
    COL_INDEX,
    COL_PROJECT,
    COL_SAMPLE,
    COL_STANDARDS,
    COL_STATUS,
    COL_TESTS,
    COL_TO,
    ProjectBoardPage,
    ProjectIdLink,
)
from src.ui.test_detail_dialog import TestDetailDialog


TODAY = date(2026, 9, 1)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _save(root: Path, state: ProjectState) -> None:
    state.save_to_file(str(root / state.project_id / "project_state.json"))


def _incomplete_node(name: str, start: str, end: str) -> TestNode:
    return TestNode(test_name=name, start_date=start, end_date=end)


def _complete_node(name: str, start: str, end: str) -> TestNode:
    return TestNode(
        test_name=name,
        start_date=start,
        end_date=end,
        standards=[
            TestStandard(standard_id="GB/T 1", chapter="1", test_name=name)
        ],
        equipments=[TestEquipment(name="温箱", code="H001")],
        samples=[TestSample(sample_id="A01")],
    )


def test_board_gate_dialog_f_enters_without_input():
    _app()
    dialog = BoardGateDialog()
    dialog.show()
    QApplication.processEvents()
    assert dialog.findChild(QLineEdit) is None
    assert dialog.lbl_hint.text() == "按【F】键进入坦克"
    QTest.keyClick(dialog, Qt.Key_F)
    QApplication.processEvents()
    assert dialog.result() == QDialog.Accepted
    dialog.close()


def test_board_gate_dialog_escape_cancels():
    _app()
    dialog = BoardGateDialog()
    dialog.show()
    QApplication.processEvents()
    QTest.keyClick(dialog, Qt.Key_Escape)
    QApplication.processEvents()
    assert dialog.result() == QDialog.Rejected
    dialog.close()


def test_board_page_one_row_per_card_and_progress(tmp_path):
    _app()
    _save(
        tmp_path,
        ProjectState(
            project_id="A22605082131",
            applicant_name="均胜",
            sample_name="主气囊",
            tester_name="黄佳林",
            test_end_date="2026-08-20",
            application_fields={"送样数量": "6"},
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
                    nodes=[_complete_node("振动试验", "2026-06-01", "2026-07-01")],
                )
            ],
        ),
    )
    page = ProjectBoardPage(tmp_path)
    page.reload(today=TODAY)
    assert page.tree.topLevelItemCount() == 2
    assert page.tree.headerItem().text(COL_STATUS) == "项目状态"
    headers = [page.tree.headerItem().text(i) for i in range(page.tree.columnCount())]
    assert "试验员" not in headers
    assert "委托方" not in BOARD_COLUMNS

    parent = next(
        page.tree.topLevelItem(i)
        for i in range(page.tree.topLevelItemCount())
        if page.tree.topLevelItem(i).data(COL_PROJECT, Qt.UserRole) == "A22605082131"
    )
    assert parent.isExpanded() is False
    assert parent.text(COL_END) == "2026-09-20"
    assert parent.text(COL_STATUS) == ""
    parent_bar = page.tree.itemWidget(parent, COL_STATUS)
    assert isinstance(parent_bar, QProgressBar)
    assert parent_bar.format() == "62%"

    on_track = next(
        page.tree.topLevelItem(i)
        for i in range(page.tree.topLevelItemCount())
        if page.tree.topLevelItem(i).data(COL_PROJECT, Qt.UserRole) == "A22602199091"
    )
    on_track_bar = page.tree.itemWidget(on_track, COL_STATUS)
    assert isinstance(on_track_bar, QProgressBar)
    assert on_track_bar.objectName() != "overdueProgress"
    assert "#0A0E14" in on_track_bar.styleSheet()
    link = page.tree.itemWidget(parent, COL_PROJECT)
    assert isinstance(link, ProjectIdLink)
    assert "A22605082131" in link.text()
    assert parent.text(COL_PROJECT) == ""

    overdue = next(
        parent.child(j)
        for j in range(parent.childCount())
        if parent.child(j).text(COL_TESTS) == "高温试验"
    )
    bar = page.tree.itemWidget(overdue, COL_STATUS)
    assert isinstance(bar, QProgressBar)
    assert bar.objectName() == "overdueProgress"
    assert "#E6EDF3" in bar.styleSheet()
    assert overdue.text(COL_STATUS) == ""
    assert overdue.text(COL_END) == "2026-08-20"
    assert overdue.text(COL_TO) == ""

    page.txt_search.setText("均胜")
    QApplication.processEvents()
    assert page.tree.topLevelItemCount() == 1
    assert page.tree.topLevelItem(0).isExpanded() is True
    assert page.lbl_count.text() == "1 个项目 · 2 个试验"


def test_board_tree_expand_shows_per_test_to(tmp_path):
    _app()
    _save(
        tmp_path,
        ProjectState(
            project_id="A22606909401",
            sample_name="司机气囊",
            to_numbers=["TO-26112398-04", "TO-26112398-05"],
            to_numbers_display="TO-26112398-04/05",
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
                        ),
                        TestNode(
                            test_name="高温老化",
                            start_date="2026-08-11",
                            end_date="2026-09-10",
                            selected_to="TO-26112398-05",
                        ),
                    ],
                )
            ],
        ),
    )
    page = ProjectBoardPage(tmp_path)
    page.reload(today=TODAY)
    parent = page.tree.topLevelItem(0)
    assert parent.isExpanded() is False
    assert parent.text(COL_TO) == ""
    assert parent.text(COL_INDEX).startswith("▶")
    page.tree.itemClicked.emit(parent, COL_PROJECT)
    QApplication.processEvents()
    assert parent.isExpanded() is False
    page.tree.itemClicked.emit(parent, COL_INDEX)
    QApplication.processEvents()
    assert parent.isExpanded() is True
    assert parent.text(COL_INDEX).startswith("▼")
    tos = {parent.child(i).text(COL_TO) for i in range(parent.childCount())}
    names = {parent.child(i).text(COL_TESTS) for i in range(parent.childCount())}
    assert tos == {"TO-26112398-04", "TO-26112398-05"}
    assert names == {"湿热老化", "高温老化"}
    ends = {parent.child(i).text(COL_END) for i in range(parent.childCount())}
    assert ends == {"2026-08-28", "2026-09-10"}
    assert parent.text(COL_END) == "2026-09-10"


def test_f_unlocks_board_and_back_returns():
    _app()
    win = MainWindow()
    assert win._stack.currentWidget() is win._report_page
    assert win._unlock_project_board() is True
    assert win._stack.currentWidget() is win._board_page
    win._board_page.btn_back.click()
    QApplication.processEvents()
    assert win._stack.currentWidget() is win._report_page


def test_search_expands_drawer_and_highlights_hit(tmp_path):
    _app()
    _save(
        tmp_path,
        ProjectState(
            project_id="A2260715291101",
            sample_name="方向盘总成",
            legs=[
                TestLeg(
                    leg_id="L1",
                    leg_name="Leg 1",
                    nodes=[
                        _incomplete_node("环境交变试验", "2026-08-18", "2026-08-28"),
                        TestNode(
                            test_name="耐寒性能",
                            start_date="2026-08-18",
                            end_date="2026-09-07",
                            standards=[
                                TestStandard(
                                    standard_id="Q/JLY J7110520C-2021",
                                    chapter="8.3.4",
                                    test_name="耐寒性能",
                                )
                            ],
                        ),
                    ],
                )
            ],
        ),
    )
    page = ProjectBoardPage(tmp_path)
    page.reload(today=TODAY)
    parent = page.tree.topLevelItem(0)
    assert parent.isExpanded() is False
    page.txt_search.setText("耐寒")
    QApplication.processEvents()
    parent = page.tree.topLevelItem(0)
    assert parent.isExpanded() is True
    assert parent.childCount() == 1
    assert parent.child(0).text(COL_TESTS) == "耐寒性能"

    page.txt_search.setText("A2260715291101")
    QApplication.processEvents()
    parent = page.tree.topLevelItem(0)
    link = page.tree.itemWidget(parent, COL_PROJECT)
    assert isinstance(link, ProjectIdLink)
    assert "background-color" in link.text()


def test_standards_column_fits_id_and_chapter(tmp_path):
    _app()
    label = "Q/JLY J7110520C-2021 / 8.3.4"
    _save(
        tmp_path,
        ProjectState(
            project_id="A22600000010",
            sample_name="方向盘总成加长样品名称",
            legs=[
                TestLeg(
                    leg_id="L1",
                    leg_name="Leg 1",
                    nodes=[
                        TestNode(
                            test_name="耐寒性能",
                            start_date="2026-08-18",
                            end_date="2026-09-07",
                            standards=[
                                TestStandard(
                                    standard_id="Q/JLY J7110520C-2021",
                                    chapter="8.3.4",
                                    test_name="耐寒性能",
                                )
                            ],
                        )
                    ],
                )
            ],
        ),
    )
    page = ProjectBoardPage(tmp_path)
    page.show()
    page.reload(today=TODAY)
    QApplication.processEvents()
    parent = page.tree.topLevelItem(0)
    child = parent.child(0)
    assert child.text(COL_STANDARDS) == label
    needed = page.tree.fontMetrics().horizontalAdvance(label)
    assert page.tree.columnWidth(COL_STANDARDS) >= needed
    sample_needed = page.tree.fontMetrics().horizontalAdvance("方向盘总成加长样品名称")
    assert page.tree.columnWidth(COL_SAMPLE) >= sample_needed
    page.close()


def test_board_columns_match_form():
    assert BOARD_COLUMNS == (
        "序号",
        "项目号",
        "样品名称",
        "TO号",
        "试验项目",
        "标准",
        "项目状态",
        "开始时间",
        "结束时间",
        "样品数量",
        "备注",
    )
    assert "委托方" not in BOARD_COLUMNS
    assert "试验员" not in BOARD_COLUMNS


def test_detail_dialog_to_combo_uses_full_names():
    _app()

    class Host(QWidget):
        def __init__(self):
            super().__init__()
            self.state = ProjectState(
                project_id="A1",
                to_numbers=["TO-1234-01", "TO-1234-02", "TO-1234-03"],
                to_numbers_display="TO-1234-01/02/03",
            )

    host = Host()
    node = TestNode(test_name="湿热老化", selected_to="TO-1234-02")
    dlg = TestDetailDialog(node, [], [], host)
    texts = [dlg.cmb_to.itemText(i) for i in range(dlg.cmb_to.count())]
    assert "TO-1234-01" in texts
    assert "TO-1234-02" in texts
    assert "TO-1234-03" in texts
    assert "TO-1234-01/02/03" not in texts
    assert dlg.cmb_to.currentData() == "TO-1234-02"
    dlg.cmb_to.setCurrentIndex(dlg.cmb_to.findData("TO-1234-03"))
    assert dlg._apply_schedule_dates() is True
    assert dlg.node_data.selected_to == "TO-1234-03"
    assert dlg.lbl_to.text() == "TO:"
    assert dlg.cmb_to.maximumWidth() <= 200
    assert dlg.txt_env_condition.minimumWidth() >= 200
    dlg.close()
