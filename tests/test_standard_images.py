import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.models.project_state import TestNode, TestStandard
from src.parsers.db_loader import BaseDataLoader, DuplicateStandardError
from src.parsers.xlsx_images import load_xlsx_row_images
from src.ui.test_detail_dialog import (
    DrawerSection,
    StdImageLink,
    TestDetailDialog,
    _image_link_text,
)

_MIN_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)
_LIB = Path("database/标准库.xlsx")


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_image_link_caption():
    assert _image_link_text(1, 1) == "图片"
    assert _image_link_text(1, 2) == "图片1"
    assert _image_link_text(2, 2) == "图片2"


def test_library_attaches_example_image():
    assert _LIB.exists()
    by_row = load_xlsx_row_images(_LIB)
    assert 4 in by_row
    assert by_row[4][0].startswith(b"\x89PNG")

    loader = BaseDataLoader()
    try:
        loaded = loader.load_standards()
    except DuplicateStandardError:
        loaded = None
    if loaded is not None:
        hit = None
        for rec in loaded:
            if rec.get("标准号") == "VW82511-2010" and str(rec.get("章节号")) == "8.3.4":
                hit = rec
                break
        assert hit is not None
        assert len(hit["_images"]) == 1
        assert hit["_images"][0] == by_row[4][0]
    else:
        rec = None
        import pandas as pd
        df = pd.read_excel(_LIB).fillna("")
        for index, row in df.iterrows():
            if row.get("标准号") == "VW82511-2010" and str(row.get("章节号")) == "8.3.4":
                rec = row
                blobs = by_row.get(index + 2, [])
                assert blobs and blobs[0] == by_row[4][0]
                break
        assert rec is not None


def test_condition_header_shows_image_and_full_title():
    _app()
    png_a = _MIN_PNG
    png_b = _MIN_PNG + b""
    node = TestNode(test_name="振动")
    standards = [
        {
            "标准号": "VW82511-2010",
            "章节号": "8.3.4",
            "试验名称": "振动应力叠加温度环境试验",
            "标准描述": "条件甲",
            "评价要求": "要求甲",
            "结果描述": "描述甲",
            "_images": [png_a, png_b],
        },
        {
            "标准号": "VW82511-2010",
            "章节号": "8.3.5",
            "试验名称": "环境循环试验",
            "标准描述": "条件乙",
            "评价要求": "要求乙",
            "结果描述": "描述乙",
            "_images": [],
        },
    ]
    dlg = TestDetailDialog(node, standards, [])
    try:
        dlg.std_table.item(0, 0).setCheckState(Qt.Checked)
        dlg.std_table.item(1, 0).setCheckState(Qt.Checked)
        dlg.show()
        assert len(dlg._cond_drawers) == 2
        first = dlg._cond_drawers[0]
        title = "振动应力叠加温度环境试验"
        assert first.lbl_title.text() == title
        assert "…" not in first.lbl_title.text()
        links = first.image_host.findChildren(StdImageLink)
        assert [lnk.text() for lnk in links] == ["图片1", "图片2"]
        assert not first.image_host.isHidden()
        assert first.accessory.isHidden()

        second = dlg._cond_drawers[1]
        assert second.lbl_title.text() == "环境循环试验"
        assert not second.image_host.findChildren(StdImageLink)
        assert not second.image_host.isVisible()

        eval_first = dlg._eval_drawers[0]
        assert eval_first.lbl_title.text() == title
        assert not eval_first.image_host.findChildren(StdImageLink)

        assert dlg.result_desc_table.columnCount() == 2
        assert dlg.result_desc_table.horizontalHeaderItem(0).text() == "试验名称"
        assert dlg.result_desc_table.horizontalHeaderItem(1).text() == "结果描述"
        assert dlg.result_desc_table.item(0, 0).text() == title
        assert dlg.result_desc_table.item(1, 0).text() == "环境循环试验"

        links[0].toggle_preview()
        assert links[0]._popup is not None
        assert links[0]._popup.isVisible()
        links[0].toggle_preview()
        assert links[0]._popup is None
    finally:
        dlg.close()


def test_wrap_title_drawer_keeps_full_text():
    _app()
    title = "VW82511-2010，章节号 8.3.4，振动应力叠加温度环境试验"
    drawer = DrawerSection(title, wrap_title=True)
    drawer.set_images([_MIN_PNG])
    drawer.resize(420, 80)
    assert drawer.lbl_title.text() == title
    assert drawer.image_host.findChildren(StdImageLink)[0].text() == "图片"


def test_restore_matches_by_standard_and_chapter_keeps_project_snapshot():
    _app()
    node = TestNode(test_name="试验A2")
    node.apply_standards(
        [
            TestStandard(
                standard_id="ABC",
                chapter="1.1",
                test_name="试验A",
                standard_desc="项目里改过的条件",
                result_desc="项目里改过的结果",
                evaluation_req="项目里改过的要求",
                images=[_MIN_PNG],
            )
        ]
    )
    catalog = [
        {
            "标准号": "ABC",
            "章节号": "1.1",
            "试验名称": "库里的试验名称",
            "标准描述": "库里的条件",
            "评价要求": "库里的要求",
            "结果描述": "库里的结果",
            "_images": [],
        }
    ]
    dlg = TestDetailDialog(node, catalog, [])
    try:
        assert dlg.std_table.item(0, 0).checkState() == Qt.Checked
        picked = dlg._selected_standards()
        assert len(picked) == 1
        assert picked[0].test_name == "库里的试验名称"
        assert picked[0].standard_desc == "项目里改过的条件"
        assert picked[0].result_desc == "项目里改过的结果"
        assert picked[0].evaluation_req == "项目里改过的要求"
        assert picked[0].images == [_MIN_PNG]
        links = dlg._cond_drawers[0].image_host.findChildren(StdImageLink)
        assert [lnk.text() for lnk in links] == ["图片"]
    finally:
        dlg.close()


if __name__ == "__main__":
    test_image_link_caption()
    test_library_attaches_example_image()
    test_condition_header_shows_image_and_full_title()
    test_wrap_title_drawer_keeps_full_text()
    test_restore_matches_by_standard_and_chapter_keeps_project_snapshot()
    print("test_standard_images: ok")
