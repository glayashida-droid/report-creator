import os
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image

from src.io.test_photos import (
    PhotoError,
    apply_album_order,
    collect_drop_images,
    copy_into_album,
    copy_into_album_keep_names,
    create_album,
    create_template_albums,
    delete_test_dir,
    hooked_test_dir_key,
    infer_numbered_prefix,
    iter_export_photos,
    list_albums,
    list_photos,
    next_sequence,
    numbered_name,
    remap_album_order,
    rename_album,
    rename_all_in_album,
    rename_photo,
    rename_test_dir,
    renumber_photos,
    RENAME_CONFLICT_MESSAGE,
    test_dir_key as leg_test_dir_key,
    uses_data_photo_layout,
)

LEG = "Leg 1"
LEG2 = "Leg 2"


def _dir(root: Path, test_name: str, leg_name: str = LEG) -> Path:
    return root / "3.测试组" / leg_test_dir_key(leg_name, test_name)


def _png(path: Path, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path, "PNG")
    return path


def _jpeg(path: Path, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path, "JPEG")
    return path


def _jpeg_with_exif(path: Path, shot_at: str, color="blue"):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (8, 8), color)
    exif = img.getexif()
    exif[306] = shot_at
    img.save(path, "JPEG", exif=exif)
    return path


def test_test_dir_key_uses_leg_prefix():
    assert leg_test_dir_key("Leg 1", "温湿度试验") == "Leg 1-温湿度试验"


def test_list_albums_order_and_ignores_loose_and_nested():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test = _dir(root, "高温试验")
        (test / "曲线").mkdir(parents=True)
        (test / "试验前").mkdir()
        (test / "数据").mkdir()
        (test / "试验前" / "nested").mkdir()
        _png(test / "loose.png")
        _png(test / "试验前" / "a.png")
        _png(test / "试验前" / "nested" / "hidden.png")
        _png(test / "曲线" / "b.png")

        assert list_albums(root, LEG, "高温试验") == ["试验前", "数据", "曲线"]
        photos = list_photos(root, LEG, "高温试验", "试验前")
        assert [p.name for p in photos] == ["a.png"]
        exported = [p.name for p in iter_export_photos(root, LEG, "高温试验")]
        assert exported == ["a.png", "b.png"]
        assert list_albums(root, LEG, "请选择试验...") == []
        assert iter_export_photos(root, LEG, "别的试验") == []


def test_list_albums_excludes_spare_folder():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test = _dir(root, "高温试验")
        (test / "试验前").mkdir(parents=True)
        (test / "备用").mkdir()
        assert list_albums(root, LEG, "高温试验") == ["试验前"]


def test_template_skips_existing_and_custom_rejects_duplicate():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (_dir(root, "高温试验") / "试验前").mkdir(parents=True)
        created = create_template_albums(root, LEG, "高温试验")
        assert created == ["试验中", "数据", "试验后"]
        assert list_albums(root, LEG, "高温试验") == ["试验前", "试验中", "数据", "试验后"]
        assert create_template_albums(root, LEG, "高温试验") == []
        create_album(root, LEG, "高温试验", "样品外观")
        try:
            create_album(root, LEG, "高温试验", "样品外观")
            raise AssertionError("expected duplicate error")
        except PhotoError:
            pass
        try:
            create_album(root, LEG, "高温试验", "a/b")
            raise AssertionError("expected illegal name")
        except PhotoError:
            pass


def test_copy_continues_sequence_and_drop_reads_one_level():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        album = create_album(root, LEG, "高温试验", "试验前")
        first = _png(Path(tmp) / "src" / "one.png", "red")
        second = _png(Path(tmp) / "src" / "two.png", "green")
        written = copy_into_album(album, [first, second], "试验前")
        assert [p.name for p in written] == ["试验前-001.png", "试验前-002.png"]
        third = _png(Path(tmp) / "src" / "three.png", "blue")
        more = copy_into_album(album, [third], "试验前")
        assert more[0].name == "试验前-003.png"
        assert next_sequence(album, "试验前") == 4
        other = copy_into_album(album, [first], "样品")
        assert other[0].name == "样品-001.png"

        drop_dir = Path(tmp) / "bundle"
        nested = drop_dir / "deep"
        nested.mkdir(parents=True)
        _png(drop_dir / "ok.png")
        _png(nested / "nope.png")
        (drop_dir / "notes.txt").write_text("x", encoding="utf-8")
        images, skipped = collect_drop_images([drop_dir, Path(tmp) / "src" / "two.png"])
        names = sorted(p.name for p in images)
        assert names == ["ok.png", "two.png"]
        assert "notes.txt" in skipped
        assert "nope.png" not in names


def test_rename_all_uses_exif_then_mtime():
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "album"
        album.mkdir()
        later = _jpeg_with_exif(album / "later.jpg", "2026:02:01 10:00:00", "red")
        earlier = _jpeg_with_exif(album / "earlier.jpg", "2026:01:01 10:00:00", "green")
        no_exif = _png(album / "shot.png", "blue")
        old = datetime(2025, 1, 1).timestamp()
        os.utime(no_exif, (old, old))
        renamed = rename_all_in_album(album, "试验前")
        assert [p.name for p in renamed] == [
            "试验前-001.png",
            "试验前-002.jpg",
            "试验前-003.jpg",
        ]
        assert numbered_name("A2260613686101", 1, ".JPG") == "A2260613686101-001.jpg"
        assert numbered_name("试验前", 1, ".jpeg") == "试验前-001.jpg"
        assert numbered_name("试验前", 2, ".PNG") == "试验前-002.png"


def test_rename_photo_stem_identity_and_jpeg_suffix():
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "album"
        album.mkdir()
        _png(album / "试验前-001.png", "red")
        src = _jpeg(album / "cam.jpeg", "green")
        try:
            rename_photo(src, "试验前-001")
            raise AssertionError("expected stem conflict")
        except PhotoError:
            pass
        renamed = rename_photo(src, "样品")
        assert renamed.name == "样品.jpg"
        assert renamed.exists()
        assert not (album / "cam.jpeg").exists()


def test_keep_original_stem_collision_ignores_extension():
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "album"
        album.mkdir()
        _png(album / "shot.png", "red")
        src = _jpeg(Path(tmp) / "src" / "shot.jpg", "green")
        written = copy_into_album_keep_names(album, [src])
        assert written[0].name == "shot_1.jpg"


def test_copy_into_album_canonicalizes_jpeg_suffix():
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "album"
        album.mkdir()
        src = _jpeg(Path(tmp) / "src" / "cam.jpeg", "blue")
        written = copy_into_album(album, [src], "试验前")
        assert written[0].name == "试验前-001.jpg"


def test_renumber_photos_keeps_given_order_not_exif():
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "album"
        album.mkdir()
        later = _jpeg_with_exif(album / "later.jpg", "2026:02:01 10:00:00", "red")
        earlier = _jpeg_with_exif(album / "earlier.jpg", "2026:01:01 10:00:00", "green")
        jpeg = _jpeg(album / "mid.jpeg", "blue")
        renamed = renumber_photos(album, "试验前", [later, jpeg, earlier])
        assert [p.name for p in renamed] == [
            "试验前-001.jpg",
            "试验前-002.jpg",
            "试验前-003.jpg",
        ]
        with Image.open(album / "试验前-001.jpg") as img:
            assert img.getpixel((0, 0))[0] >= 200
        with Image.open(album / "试验前-002.jpg") as img:
            assert img.getpixel((0, 0))[2] >= 200


def test_infer_numbered_prefix():
    assert infer_numbered_prefix(["试验前-001.jpg", "试验前-002.png"]) == "试验前"
    assert infer_numbered_prefix(["a.png", "b.jpg"]) is None
    assert infer_numbered_prefix(["试验前-001.jpg", "样品-002.jpg"]) is None
    assert infer_numbered_prefix(["试验前-001.jpg", "notes.png"]) == "试验前"


def test_rename_test_dir_blocks_existing_target():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = _dir(root, "高温试验") / "试验前"
        src.mkdir(parents=True)
        _png(src / "a.png")
        (_dir(root, "高温老化")).mkdir()
        old_key = leg_test_dir_key(LEG, "高温试验")
        new_conflict = leg_test_dir_key(LEG, "高温老化")
        new_ok = leg_test_dir_key(LEG, "高温贮存")
        try:
            rename_test_dir(root, old_key, new_conflict)
            raise AssertionError("expected conflict")
        except PhotoError as exc:
            assert str(exc) == RENAME_CONFLICT_MESSAGE
        assert (src / "a.png").exists()
        moved = rename_test_dir(root, old_key, new_ok)
        assert moved is not None
        assert (moved / "试验前" / "a.png").exists()
        assert not _dir(root, "高温试验").exists()
        assert rename_test_dir(root, "不存在", "新名字") is None
        assert rename_test_dir(root, new_ok, "") is None
        assert (_dir(root, "高温贮存") / "试验前" / "a.png").exists()


def test_rename_test_dir_success_moves_hooked_dir():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = _dir(root, "高温试验") / "试验前"
        src.mkdir(parents=True)
        _png(src / "a.png")
        old_key = leg_test_dir_key(LEG, "高温试验")
        new_key = leg_test_dir_key(LEG, "高温贮存")
        moved = rename_test_dir(root, old_key, new_key)
        assert moved == _dir(root, "高温贮存")
        assert (moved / "试验前" / "a.png").is_file()
        assert not _dir(root, "高温试验").exists()


def test_rename_test_dir_noop_when_source_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        assert rename_test_dir(root, leg_test_dir_key(LEG, "不存在"), leg_test_dir_key(LEG, "新名")) is None
        assert not (root / "3.测试组").exists()


def test_delete_test_dir_removes_existing_and_noops_when_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        key = leg_test_dir_key(LEG, "高温试验")
        hooked = _dir(root, "高温试验") / "试验前"
        hooked.mkdir(parents=True)
        _png(hooked / "a.png")
        assert hooked_test_dir_key(root, LEG, "高温试验") == key
        assert hooked_test_dir_key(root, LEG, "未挂钩") is None
        delete_test_dir(root, key)
        assert not _dir(root, "高温试验").exists()
        delete_test_dir(root, key)
        delete_test_dir(root, "")


def test_rename_album_keeps_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        album = create_album(root, LEG, "高温试验", "试验前")
        _png(album / "试验前-001.png")
        renamed = rename_album(root, LEG, "高温试验", "试验前", "预处理")
        assert renamed.name == "预处理"
        assert (renamed / "试验前-001.png").exists()


def test_copy_keep_original_names_and_collision():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        album = create_album(root, LEG, "高温试验", "试验前")
        src_dir = Path(tmp) / "src"
        a = _png(src_dir / "微信图片_001.png", "red")
        b = _png(src_dir / "外观检查.png", "green")
        written = copy_into_album_keep_names(album, [a, b])
        assert [p.name for p in written] == ["微信图片_001.png", "外观检查.png"]
        again = copy_into_album_keep_names(album, [a])
        assert again[0].name == "微信图片_001_1.png"
        assert (album / "微信图片_001.png").exists()


def test_rename_photo_validates_and_keeps_suffix():
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp) / "album"
        album.mkdir()
        src = _png(album / "old.png", "red")
        _png(album / "taken.png", "blue")
        renamed = rename_photo(src, "新样品")
        assert renamed.name == "新样品.png"
        assert renamed.exists()
        try:
            rename_photo(renamed, "taken.png")
            raise AssertionError("expected conflict")
        except PhotoError:
            pass
        try:
            rename_photo(renamed, "a/b.png")
            raise AssertionError("expected illegal")
        except PhotoError:
            pass


def test_export_list_skips_old_plain_test_name_path():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _png(_dir(root, "高温试验") / "试验前" / "keep.png")
        _png(_dir(root, "高温试验") / "loose.png")
        _png(root / "3.测试组" / "高温试验" / "试验前" / "legacy.png")
        _png(root / "3.测试组" / "TO-高温试验" / "fuzzy.png")
        names = [p.name for p in iter_export_photos(root, LEG, "高温试验")]
        assert names == ["keep.png"]


def test_cross_leg_same_test_name_gets_separate_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_album(root, LEG, "温湿度试验", "试验前")
        create_album(root, LEG2, "温湿度试验", "试验前")
        assert (_dir(root, "温湿度试验", LEG) / "试验前").is_dir()
        assert (_dir(root, "温湿度试验", LEG2) / "试验前").is_dir()
        assert list_albums(root, LEG, "温湿度试验") == ["试验前"]
        assert list_albums(root, LEG2, "温湿度试验") == ["试验前"]


def test_unusable_test_name_cannot_create_album():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for bad in ("", "请选择试验...", "自定义"):
            try:
                create_album(root, LEG, bad, "试验前")
                raise AssertionError(f"expected PhotoError for {bad!r}")
            except PhotoError:
                pass
        assert not (root / "3.测试组").exists()


def test_lazy_hook_card_only_does_not_create_test_dir(tmp_path):
    import sys

    from PySide6.QtWidgets import QApplication

    from src.models.project_state import ProjectState
    from src.ui.leg_graph import LegGraphArea

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    state = ProjectState(project_id="P1", project_path=str(tmp_path))
    area = LegGraphArea(state)
    area.add_leg()
    lw = area.leg_widgets[0]
    lw.on_add_node()
    nw = lw.node_widgets[0]
    nw._commit_test_name("高温试验")
    assert not (tmp_path / "3.测试组").exists()


def test_add_template_blocked_when_same_leg_duplicate(tmp_path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication

    from src.models.project_state import ProjectState, TestLeg, TestNode
    from src.ui.test_photos_panel import TestPhotosPanel

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[
                    TestNode(test_name="湿热循环"),
                    TestNode(test_name="湿热循环"),
                ],
            )
        ],
    )
    node = state.legs[0].nodes[0]
    panel = TestPhotosPanel(
        tmp_path,
        "Leg 1",
        "湿热循环",
        "P1",
        project_state=state,
        node_data=node,
    )
    with patch("src.ui.test_photos_panel.warn_duplicate_test_names") as warn:
        panel._add_template()
        warn.assert_called_once()
    assert not (tmp_path / "3.测试组").exists()


def test_photos_panel_shows_spare_album_last(tmp_path):
    import sys

    from PySide6.QtWidgets import QApplication

    from src.io.project_assets import move_photo_to_spare
    from src.io.test_photos import SPARE_ALBUM_NAME, create_template_albums
    from src.models.project_state import ProjectState, TestLeg, TestNode
    from src.ui.test_photos_panel import PHOTO_PATH_ROLE, TestPhotosPanel

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="高温试验")],
            )
        ],
    )
    node = state.legs[0].nodes[0]
    create_template_albums(tmp_path, "Leg 1", "高温试验")
    shot = _png(_dir(tmp_path, "高温试验") / "试验前" / "shot.png")
    rel = shot.relative_to(tmp_path).as_posix()
    move_photo_to_spare(tmp_path, None, rel)

    panel = TestPhotosPanel(
        tmp_path,
        "Leg 1",
        "高温试验",
        "P1",
        project_state=state,
        node_data=node,
    )
    names = [row.album_name for row in panel._row_widgets()]
    assert names[-1] == SPARE_ALBUM_NAME
    assert names[:-1] == ["试验前", "试验中", "数据", "试验后"]
    assert SPARE_ALBUM_NAME not in panel.current_album_order()
    album_count, photo_count = panel.counts()
    assert album_count == 4
    assert photo_count == 0

    spare = panel._spare_row()
    assert spare is not None
    assert spare.btn_delete.isHidden()
    assert spare.btn_qr.isHidden()
    assert spare.btn_rename_all.text() == "打开文件夹"
    formal = next(row for row in panel._row_widgets() if not row.is_spare)
    assert not formal.btn_qr.isHidden()
    assert formal.btn_qr.text() == "QR"
    thumbs = spare.gallery
    assert thumbs.count() == 1
    item = thumbs.item(0)
    assert Path(item.data(PHOTO_PATH_ROLE)).name == "shot.png"
    assert item.toolTip() == "shot.png"
    assert thumbs.dragEnabled() is False


def test_open_spare_folder_prefers_remote(tmp_path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QMessageBox

    from src.io.project_assets import spare_dir
    from src.models.project_state import ProjectState, TestLeg, TestNode
    from src.ui.test_photos_panel import TestPhotosPanel

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    remote.mkdir()
    state = ProjectState(
        project_id="P1",
        source_path=str(remote),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="高温试验")],
            )
        ],
    )
    panel = TestPhotosPanel(
        local,
        "Leg 1",
        "高温试验",
        "P1",
        project_state=state,
        node_data=state.legs[0].nodes[0],
    )
    with patch("src.ui.test_photos_panel.open_folder_in_file_manager") as mock_open:
        with patch.object(QMessageBox, "information") as mock_info:
            panel._open_spare_folder()
    mock_open.assert_called_once_with(spare_dir(remote, "Leg 1", "高温试验"))
    mock_info.assert_not_called()


def test_open_spare_folder_falls_back_to_local_with_prompt(tmp_path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QMessageBox

    from src.io.project_assets import spare_dir
    from src.models.project_state import ProjectState, TestLeg, TestNode
    from src.ui.test_photos_panel import TestPhotosPanel

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    local = tmp_path / "local"
    local.mkdir()
    offline = tmp_path / "offline-remote"
    state = ProjectState(
        project_id="P1",
        source_path=str(offline),
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg 1",
                nodes=[TestNode(test_name="高温试验")],
            )
        ],
    )
    panel = TestPhotosPanel(
        local,
        "Leg 1",
        "高温试验",
        "P1",
        project_state=state,
        node_data=state.legs[0].nodes[0],
    )
    with patch("src.ui.test_photos_panel.open_folder_in_file_manager") as mock_open:
        with patch.object(QMessageBox, "information") as mock_info:
            panel._open_spare_folder()
    mock_info.assert_called_once()
    assert "公盘不可达" in mock_info.call_args.args[2]
    mock_open.assert_called_once_with(spare_dir(local, "Leg 1", "高温试验"))


def test_photo_thumb_delete_hover_uses_arrow_cursor(tmp_path):
    import sys

    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtWidgets import QApplication

    from src.io.test_photos import create_album
    from src.ui.test_photos_panel import (
        PHOTO_CLOUD_ROLE,
        _cloud_pixmap,
        _delete_btn_rect,
        _download_btn_rect,
        PhotoAlbumRow,
    )

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    album = create_album(tmp_path, "Leg 1", "高温试验", "试验前")
    _png(album / "试验前-001.png")
    row = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验前", "P1")
    gallery = row.gallery
    assert gallery.hasMouseTracking()
    assert gallery.viewport().hasMouseTracking()
    assert gallery.cursor().shape() == Qt.OpenHandCursor
    assert row.btn_delete.cursor().shape() == Qt.ArrowCursor

    item = gallery.item(0)
    rect = QRect(0, 0, 90, 100)
    delete_pos = _delete_btn_rect(rect).center()
    assert gallery._hotspot_kind(delete_pos, item, rect) == "delete"
    item.setData(PHOTO_CLOUD_ROLE, False)
    assert gallery._hotspot_kind(rect.center(), item, rect) is None
    item.setData(PHOTO_CLOUD_ROLE, True)
    assert gallery._hotspot_kind(_download_btn_rect(rect).center(), item, rect) == "download"
    gallery._dragging = True
    assert gallery._cursor_for_pos(QPoint(0, 0)) == Qt.ClosedHandCursor
    gallery._dragging = False

    cloud = _cloud_pixmap()
    assert cloud.devicePixelRatio() == 2
    assert cloud.deviceIndependentSize().width() == 18
    assert cloud.deviceIndependentSize().height() == 18


def test_insert_index_for_thumbs_reading_order():
    from PySide6.QtCore import QPoint, QRect

    from src.ui.test_photos_panel import insert_index_for_rects, move_list_item

    names = ["a", "b", "c"]
    assert move_list_item(names, 0, 2) == ["b", "a", "c"]
    assert move_list_item(names, 0, 3) == ["b", "c", "a"]
    assert move_list_item(names, 2, 0) == ["c", "a", "b"]
    assert move_list_item(names, 1, 1) == ["a", "b", "c"]
    assert move_list_item(names, 1, 2) == ["a", "b", "c"]
    rects = [QRect(0, 0, 80, 80), QRect(90, 0, 80, 80)]
    assert insert_index_for_rects(rects, QPoint(10, 40)) == 0
    assert insert_index_for_rects(rects, QPoint(120, 40)) == 1
    assert insert_index_for_rects(rects, QPoint(200, 40)) == 2


def test_photo_thumb_tooltip_shows_filename(tmp_path):
    import sys

    from PySide6.QtWidgets import QApplication

    from src.io.test_photos import create_album
    from src.ui.test_photos_panel import PhotoAlbumRow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    album = create_album(tmp_path, "Leg 1", "高温试验", "试验前")
    _png(album / "试验前-001.png")
    row = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验前", "P1")
    item = row.gallery.item(0)
    assert item is not None
    assert item.text() == "试验前-001.png"
    assert item.toolTip() == "试验前-001.png"


def test_photo_thumb_cloud_tooltip_allows_rename(tmp_path):
    import sys

    from PySide6.QtWidgets import QApplication

    from src.io.test_photos import create_album
    from src.ui.test_photos_panel import PhotoAlbumRow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    create_album(remote, "Leg 1", "高温试验", "试验前")
    _png(_dir(remote, "高温试验") / "试验前" / "cloud.png")
    row = PhotoAlbumRow(
        local, "Leg 1", "高温试验", "试验前", "P1", remote_root=remote
    )
    item = row.gallery.item(0)
    assert item is not None
    assert item.toolTip() == "cloud.png"
    assert row.gallery.dragEnabled() is False
    assert row.gallery.acceptDrops() is True


def test_photo_album_row_reorder_rewrites_sequence(tmp_path):
    import sys

    from PySide6.QtWidgets import QApplication

    from src.io.test_photos import create_album
    from src.ui.test_photos_panel import PhotoAlbumRow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    album = create_album(tmp_path, "Leg 1", "高温试验", "试验前")
    _png(album / "试验前-001.png", "red")
    _png(album / "试验前-002.png", "blue")
    row = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验前", "P1")
    rels = row.gallery.ordered_rels()
    assert len(rels) == 2
    row._apply_photo_reorder(rels[0], 2)
    with Image.open(album / "试验前-001.png") as img:
        assert img.getpixel((0, 0))[2] >= 200
    with Image.open(album / "试验前-002.png") as img:
        assert img.getpixel((0, 0))[0] >= 200


def test_photo_thumb_live_move_commits_visual_order(tmp_path):
    import sys

    from PySide6.QtWidgets import QApplication

    from src.io.test_photos import create_album
    from src.ui.test_photos_panel import PhotoAlbumRow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    album = create_album(tmp_path, "Leg 1", "高温试验", "试验前")
    _png(album / "试验前-001.png", "red")
    _png(album / "试验前-002.png", "blue")
    row = PhotoAlbumRow(tmp_path, "Leg 1", "高温试验", "试验前", "P1")
    gallery = row.gallery
    rels = gallery.ordered_rels()
    assert len(rels) == 2
    gallery._order_at_press = list(rels)
    gallery._visual_order = [rels[1], rels[0]]
    gallery._end_reorder()
    with Image.open(album / "试验前-001.png") as img:
        assert img.getpixel((0, 0))[2] >= 200
    with Image.open(album / "试验前-002.png") as img:
        assert img.getpixel((0, 0))[0] >= 200


def test_apply_album_order_and_export_respects_preferred():
    assert apply_album_order(
        ["曲线", "试验前", "数据"], None
    ) == ["试验前", "数据", "曲线"]
    assert apply_album_order(
        ["曲线", "试验前", "数据"],
        ["曲线", "数据", "试验前", "gone"],
    ) == ["曲线", "数据", "试验前"]
    assert remap_album_order(["试验前", "试验后", "数据"], "试验后", "试验后888") == [
        "试验前",
        "试验后888",
        "数据",
    ]
    assert uses_data_photo_layout("数据")
    assert uses_data_photo_layout(" 数据 ")
    assert not uses_data_photo_layout("数据表附件")
    assert not uses_data_photo_layout("试验前")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test = _dir(root, "高温试验")
        for name in ("试验前", "数据", "试验后888"):
            (test / name).mkdir(parents=True)
            _png(test / name / f"{name}-001.png")
        order = ["试验后888", "试验前", "数据"]
        assert list_albums(root, LEG, "高温试验", order=order) == order
        exported = [p.parent.name for p in iter_export_photos(root, LEG, "高温试验", order=order)]
        assert exported == ["试验后888", "试验前", "数据"]


def test_photo_album_order_roundtrips_in_project_json():
    from src.models.project_state import ProjectState, TestLeg, TestNode

    state = ProjectState(
        project_id="P1",
        legs=[
            TestLeg(
                leg_id="L1",
                leg_name="Leg1",
                nodes=[
                    TestNode(
                        test_name="高温试验",
                        photo_album_order=["试验后888", "数据", "试验前"],
                    )
                ],
            )
        ],
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state.json"
        path.write_text(state.model_dump_json(), encoding="utf-8")
        loaded = ProjectState.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded.legs[0].nodes[0].photo_album_order == [
        "试验后888",
        "数据",
        "试验前",
    ]


if __name__ == "__main__":
    test_test_dir_key_uses_leg_prefix()
    test_list_albums_order_and_ignores_loose_and_nested()
    test_template_skips_existing_and_custom_rejects_duplicate()
    test_copy_continues_sequence_and_drop_reads_one_level()
    test_rename_all_uses_exif_then_mtime()
    test_rename_photo_stem_identity_and_jpeg_suffix()
    test_keep_original_stem_collision_ignores_extension()
    test_copy_into_album_canonicalizes_jpeg_suffix()
    test_renumber_photos_keeps_given_order_not_exif()
    test_infer_numbered_prefix()
    test_rename_test_dir_blocks_existing_target()
    test_rename_test_dir_success_moves_hooked_dir()
    test_rename_test_dir_noop_when_source_missing()
    test_delete_test_dir_removes_existing_and_noops_when_missing()
    test_rename_album_keeps_files()
    test_copy_keep_original_names_and_collision()
    test_rename_photo_validates_and_keeps_suffix()
    test_export_list_skips_old_plain_test_name_path()
    test_cross_leg_same_test_name_gets_separate_dirs()
    test_unusable_test_name_cannot_create_album()
    test_apply_album_order_and_export_respects_preferred()
    test_photo_album_order_roundtrips_in_project_json()
    print("test_test_photos: ok")
