import os
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image

from src.io.test_photos import (
    PhotoError,
    collect_drop_images,
    copy_into_album,
    copy_into_album_keep_names,
    create_album,
    create_template_albums,
    iter_export_photos,
    list_albums,
    list_photos,
    next_sequence,
    numbered_name,
    rename_album,
    rename_all_in_album,
    rename_photo,
    rename_test_dir,
)


def _png(path: Path, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path, "PNG")
    return path


def _jpeg_with_exif(path: Path, shot_at: str, color="blue"):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (8, 8), color)
    exif = img.getexif()
    exif[306] = shot_at
    img.save(path, "JPEG", exif=exif)
    return path


def test_list_albums_order_and_ignores_loose_and_nested():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test = root / "3.测试组" / "高温试验"
        (test / "曲线").mkdir(parents=True)
        (test / "试验前").mkdir()
        (test / "数据").mkdir()
        (test / "试验前" / "nested").mkdir()
        _png(test / "loose.png")
        _png(test / "试验前" / "a.png")
        _png(test / "试验前" / "nested" / "hidden.png")
        _png(test / "曲线" / "b.png")

        assert list_albums(root, "高温试验") == ["试验前", "数据", "曲线"]
        photos = list_photos(root, "高温试验", "试验前")
        assert [p.name for p in photos] == ["a.png"]
        exported = [p.name for p in iter_export_photos(root, "高温试验")]
        assert exported == ["a.png", "b.png"]
        assert list_albums(root, "请选择试验...") == []
        assert iter_export_photos(root, "别的试验") == []


def test_template_skips_existing_and_custom_rejects_duplicate():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "3.测试组" / "高温试验" / "试验前").mkdir(parents=True)
        created = create_template_albums(root, "高温试验")
        assert created == ["试验中", "试验后", "数据"]
        assert list_albums(root, "高温试验") == ["试验前", "试验中", "试验后", "数据"]
        assert create_template_albums(root, "高温试验") == []
        create_album(root, "高温试验", "样品外观")
        try:
            create_album(root, "高温试验", "样品外观")
            raise AssertionError("expected duplicate error")
        except PhotoError:
            pass
        try:
            create_album(root, "高温试验", "a/b")
            raise AssertionError("expected illegal name")
        except PhotoError:
            pass


def test_copy_continues_sequence_and_drop_reads_one_level():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        album = create_album(root, "高温试验", "试验前")
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


def test_rename_test_dir_blocks_existing_target():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "3.测试组" / "高温试验" / "试验前"
        src.mkdir(parents=True)
        _png(src / "a.png")
        (root / "3.测试组" / "高温老化").mkdir()
        try:
            rename_test_dir(root, "高温试验", "高温老化")
            raise AssertionError("expected conflict")
        except PhotoError:
            pass
        assert (src / "a.png").exists()
        moved = rename_test_dir(root, "高温试验", "高温贮存")
        assert moved is not None
        assert (moved / "试验前" / "a.png").exists()
        assert not (root / "3.测试组" / "高温试验").exists()
        assert rename_test_dir(root, "不存在", "新名字") is None
        assert rename_test_dir(root, "高温贮存", "") is None
        assert (root / "3.测试组" / "高温贮存" / "试验前" / "a.png").exists()


def test_rename_album_keeps_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        album = create_album(root, "高温试验", "试验前")
        _png(album / "试验前-001.png")
        renamed = rename_album(root, "高温试验", "试验前", "预处理")
        assert renamed.name == "预处理"
        assert (renamed / "试验前-001.png").exists()


def test_copy_keep_original_names_and_collision():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        album = create_album(root, "高温试验", "试验前")
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


def test_export_list_skips_fuzzy_and_loose_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _png(root / "3.测试组" / "高温试验" / "试验前" / "keep.png")
        _png(root / "3.测试组" / "高温试验" / "loose.png")
        _png(root / "3.测试组" / "TO-高温试验" / "fuzzy.png")
        names = [p.name for p in iter_export_photos(root, "高温试验")]
        assert names == ["keep.png"]


if __name__ == "__main__":
    test_list_albums_order_and_ignores_loose_and_nested()
    test_template_skips_existing_and_custom_rejects_duplicate()
    test_copy_continues_sequence_and_drop_reads_one_level()
    test_rename_all_uses_exif_then_mtime()
    test_rename_test_dir_blocks_existing_target()
    test_rename_album_keeps_files()
    test_copy_keep_original_names_and_collision()
    test_rename_photo_validates_and_keeps_suffix()
    test_export_list_skips_fuzzy_and_loose_files()
    print("test_test_photos: ok")
