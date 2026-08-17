import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from src.ui.candidate_pool import CHIP_PAD, CandidatePoolList, chip_display_width


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_chip_display_width_fits_text_then_caps():
    _app()
    fm = QLabel().fontMetrics()
    short = "湿热循环"
    long_name = "机械冲击 (半正弦)"
    short_w = chip_display_width(short, fm, 400)
    long_w = chip_display_width(long_name, fm, 400)
    assert short_w == fm.horizontalAdvance(short) + CHIP_PAD
    assert long_w == fm.horizontalAdvance(long_name) + CHIP_PAD
    assert long_w > short_w
    assert chip_display_width(long_name, fm, 80) == 80


def test_chips_size_to_each_name_and_show_full_text():
    _app()
    pool = CandidatePoolList()
    pool.resize(420, 140)
    pool.show()
    QApplication.processEvents()
    names = ["机械冲击 (半正弦)", "湿热循环", "盐雾腐蚀"]
    pool.set_items(names)
    QApplication.processEvents()
    chips = pool._chips
    assert [c.toolTip() for c in chips] == names
    assert chips[0].text() == "机械冲击 (半正弦)"
    assert chips[1].text() == "湿热循环"
    assert chips[2].width() < chips[0].width()
    assert chips[1].width() < chips[0].width()
    assert pool.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_chip_elides_only_when_wider_than_viewport():
    _app()
    pool = CandidatePoolList()
    pool.resize(90, 80)
    pool.show()
    QApplication.processEvents()
    long_name = "机械冲击 (半正弦) 这是一段特别长的名字"
    pool.set_items([long_name])
    QApplication.processEvents()
    chip = pool._chips[0]
    assert chip.toolTip() == long_name
    assert chip.text() != long_name
    assert chip.width() <= pool.viewport().width()


if __name__ == "__main__":
    test_chip_display_width_fits_text_then_caps()
    test_chips_size_to_each_name_and_show_full_text()
    test_chip_elides_only_when_wider_than_viewport()
    print("test_candidate_pool: ok")
