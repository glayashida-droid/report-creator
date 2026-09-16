import sys

from PIL import Image
from PySide6.QtWidgets import QApplication

from src.io.test_photos import create_album
from src.ui.test_photos_panel import THUMB, THUMB_SIZES, PhotoAlbumRow, gallery_height


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _png(path, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (12, 12), color).save(path, "PNG")
    return path


def test_album_row_zoom_buttons_sit_under_rename(tmp_path):
    _app()
    album = create_album(tmp_path, "Leg 1", "高温试验", "试验前")
    _png(album / "试验前-001.png")
    row = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验前", "P1")
    assert row.btn_zoom_in.text() == "🔍+"
    assert row.btn_zoom_out.text() == "🤌-"
    assert row.gallery._thumb == THUMB
    assert row.gallery.iconSize().width() == THUMB


def test_album_row_zoom_scales_all_thumbs_in_that_folder(tmp_path):
    _app()
    album = create_album(tmp_path, "Leg 1", "高温试验", "试验前")
    _png(album / "试验前-001.png", "red")
    _png(album / "试验前-002.png", "blue")
    row = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验前", "P1")
    start = row.gallery.iconSize().width()
    start_h = row.gallery.height()
    assert row.gallery.count() == 2
    row.btn_zoom_in.click()
    assert row.gallery._thumb == THUMB_SIZES[THUMB_SIZES.index(THUMB) + 1]
    assert row.gallery.iconSize().width() > start
    assert row.gallery.height() == gallery_height(row.gallery._thumb)
    assert row.gallery.height() > start_h
    assert row.gallery.count() == 2
    for i in range(row.gallery.count()):
        assert row.gallery.item(i).sizeHint().width() == row.gallery.iconSize().width() + 18


def test_album_row_zoom_does_not_change_other_folders(tmp_path):
    _app()
    before = create_album(tmp_path, "Leg 1", "高温试验", "试验前")
    during = create_album(tmp_path, "Leg 1", "高温试验", "试验中")
    _png(before / "试验前-001.png")
    _png(during / "试验中-001.png")
    row_before = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验前", "P1")
    row_during = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验中", "P1")
    row_before.btn_zoom_in.click()
    assert row_before.gallery.iconSize().width() > THUMB
    assert row_during.gallery.iconSize().width() == THUMB


def test_album_row_zoom_out_clamps_at_minimum(tmp_path):
    _app()
    album = create_album(tmp_path, "Leg 1", "高温试验", "试验前")
    _png(album / "试验前-001.png")
    row = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验前", "P1")
    while row.btn_zoom_out.isEnabled():
        row.btn_zoom_out.click()
    assert row.gallery._thumb == THUMB_SIZES[0]
    assert not row.btn_zoom_out.isEnabled()
    row.btn_zoom_out.click()
    assert row.gallery._thumb == THUMB_SIZES[0]
