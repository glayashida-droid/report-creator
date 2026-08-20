import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

from src.generators.word_engine import WordGenerator
from src.models.project_state import TestNode, TestResult, TestSample
from src.ui.test_detail_dialog import TestDetailDialog


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _check_first_standard(dlg):
    chk = dlg.std_table.item(0, 0)
    assert chk is not None
    chk.setCheckState(Qt.Checked)


def test_sample_table_has_result_desc_column_and_autofills_on_generate():
    _app()
    desc = "试验后模块保持完整性。"
    standards = [
        {
            "标准号": "STD-1",
            "章节号": "1.1",
            "试验名称": "机械冲击试验",
            "标准描述": "条件",
            "结果描述": desc,
            "评价要求": "要求",
        }
    ]
    dlg = TestDetailDialog(TestNode(test_name="机械冲击"), standards, [])
    assert dlg.table.columnCount() == 4
    assert [dlg.table.horizontalHeaderItem(i).text() for i in range(4)] == [
        "",
        "样品编号",
        "结果描述",
        "测试结果",
    ]

    _check_first_standard(dlg)
    dlg.txt_sample_prefix.setText("A")
    dlg.txt_sample_start.setText("01")
    dlg.txt_sample_qty.setText("2")
    dlg._generate_samples()

    assert dlg.table.rowCount() == 2
    for row in range(2):
        desc_w = dlg.table.cellWidget(row, 2)
        assert isinstance(desc_w, QLineEdit)
        assert desc_w.text() == desc
        assert desc_w.isReadOnly()


def test_save_persists_sample_result_desc():
    _app()
    desc = "保存时应写入样品。"
    standards = [
        {
            "标准号": "STD-2",
            "章节号": "2.2",
            "试验名称": "高温",
            "结果描述": desc,
        }
    ]
    dlg = TestDetailDialog(TestNode(test_name="高温"), standards, [])
    _check_first_standard(dlg)
    dlg.add_sample_row("A01", TestResult.PASS)
    dlg.save_and_close()
    assert len(dlg.node_data.samples) == 1
    assert dlg.node_data.samples[0].result_desc == desc


def test_word_sample_table_includes_result_desc(tmp_path):
    from docx import Document

    template = tmp_path / "t.docx"
    Document().save(template)
    node = TestNode(
        test_name="冲击",
        result_desc="节点级描述",
        samples=[
            TestSample(
                sample_id="A01",
                result=TestResult.PASS,
                result_desc="样品级描述",
            )
        ],
    )
    gen = WordGenerator(str(template))
    doc = Document()
    gen._append_sample_result_table(doc, node)
    table = doc.tables[0]
    assert [c.text for c in table.rows[0].cells] == ["样品编号", "结果描述", "结果"]
    assert [c.text for c in table.rows[1].cells] == ["A01", "样品级描述", "合格"]
