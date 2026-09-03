"""Project assets seam: merge local + remote photo views."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.io.project_assets import (
    download_photo_to_album,
    list_merged_albums,
    list_merged_attachment_refs,
    list_merged_photos,
    move_photo_to_spare,
    original_view_path,
    preview_path_for_photo,
    resolve_data_table_path,
    resolve_photo_path,
    restore_photo_from_spare,
    thumbnail_for_photo,
)
from src.io.test_photos import (
    SPARE_ALBUM_NAME,
    iter_export_photos,
    list_albums,
    test_dir_key as leg_test_dir_key,
)

LEG = "Leg 1"
TEST = "振动"


def _album(root: Path, album: str = "试验前") -> Path:
    path = root / "3.测试组" / leg_test_dir_key(LEG, TEST) / album
    path.mkdir(parents=True, exist_ok=True)
    return path


def _png(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path, "PNG")
    return path


def test_merged_photos_cloud_only_local_only_and_local_wins(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    _png(_album(remote) / "cloud.png", "blue")
    _png(_album(local) / "local.png", "green")
    _png(_album(remote) / "both.png", "yellow")
    _png(_album(local) / "both.png", "orange")

    merged = list_merged_photos(local, remote, LEG, TEST, "试验前")
    by_name = {Path(item.relative_path).name: item for item in merged}

    assert set(by_name) == {"cloud.png", "local.png", "both.png"}

    cloud = by_name["cloud.png"]
    assert cloud.is_cloud_only is True
    assert cloud.read_path == _album(remote) / "cloud.png"

    only_local = by_name["local.png"]
    assert only_local.is_cloud_only is False
    assert only_local.read_path == _album(local) / "local.png"

    both = by_name["both.png"]
    assert both.is_cloud_only is False
    assert both.read_path == _album(local) / "both.png"
    assert resolve_photo_path(local, remote, both.relative_path) == both.read_path


def test_merged_albums_exclude_spare_and_union_roots(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    _album(local, "试验前")
    _album(remote, "试验中")
    (_album(local).parent / "备用").mkdir(parents=True)
    (_album(remote).parent / "备用").mkdir(parents=True)
    _png(_album(local).parent / "备用" / "gone.png")

    albums = list_merged_albums(local, remote, LEG, TEST)
    assert albums == ["试验前", "试验中"]
    assert list_merged_photos(local, remote, LEG, TEST, "备用") == []


def test_thumbnail_caches_under_local_thumbs(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    src = _png(_album(remote) / "cloud.png", "blue")
    rel = src.relative_to(remote).as_posix()

    thumb1 = thumbnail_for_photo(local, rel, src, size=48)
    assert thumb1.is_file()
    assert ".thumbs" in thumb1.parts
    assert thumb1.stat().st_size > 0

    mtime = thumb1.stat().st_mtime
    thumb2 = thumbnail_for_photo(local, rel, src, size=48)
    assert thumb2 == thumb1
    assert thumb2.stat().st_mtime == mtime


def test_move_photo_to_spare_hides_from_merge_and_export(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    src = _png(_album(local) / "shot.png", "red")
    _png(_album(remote) / "shot.png", "blue")
    rel = src.relative_to(local).as_posix()

    spare_path = move_photo_to_spare(local, remote, rel)
    assert spare_path.is_file()
    assert SPARE_ALBUM_NAME in spare_path.parts
    assert not (_album(local) / "shot.png").exists()
    assert not (_album(remote) / "shot.png").exists()
    assert (_album(local).parent / SPARE_ALBUM_NAME / "shot.png").is_file()
    assert (_album(remote).parent / SPARE_ALBUM_NAME / "shot.png").is_file()

    names = {Path(p.relative_path).name for p in list_merged_photos(local, remote, LEG, TEST, "试验前")}
    assert "shot.png" not in names
    assert SPARE_ALBUM_NAME not in list_merged_albums(local, remote, LEG, TEST)
    assert SPARE_ALBUM_NAME not in list_albums(local, LEG, TEST)
    assert "shot.png" not in [p.name for p in iter_export_photos(local, LEG, TEST)]


def test_restore_photo_from_spare_returns_to_merge_list(tmp_path: Path):
    local = tmp_path / "local"
    src = _png(_album(local) / "shot.png", "red")
    rel = src.relative_to(local).as_posix()
    move_photo_to_spare(local, None, rel)

    restored = restore_photo_from_spare(local, LEG, TEST, "shot.png", "试验前")
    assert restored == _album(local) / "shot.png"
    assert restored.is_file()
    assert not (_album(local).parent / SPARE_ALBUM_NAME / "shot.png").exists()

    names = {Path(p.relative_path).name for p in list_merged_photos(local, None, LEG, TEST, "试验前")}
    assert names == {"shot.png"}


def test_download_photo_to_album_clears_cloud_only(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    src = _png(_album(remote) / "cloud.png", "blue")
    rel = src.relative_to(remote).as_posix()

    before = list_merged_photos(local, remote, LEG, TEST, "试验前")
    assert len(before) == 1 and before[0].is_cloud_only

    dest = download_photo_to_album(local, remote, rel)
    assert dest == local / rel
    assert dest.is_file()

    after = list_merged_photos(local, remote, LEG, TEST, "试验前")
    assert len(after) == 1
    assert after[0].is_cloud_only is False
    assert after[0].read_path == dest

    # already local → no-op, same path
    assert download_photo_to_album(local, remote, rel) == dest


def test_preview_and_original_do_not_pollute_album(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    src = _png(_album(remote) / "cloud.png", "blue")
    rel = src.relative_to(remote).as_posix()
    album = _album(local)
    before = {p.name for p in album.iterdir()}

    preview = preview_path_for_photo(local, remote, rel)
    assert preview.is_file()
    assert ".thumbs" in preview.parts

    view = original_view_path(local, remote, rel)
    assert view.is_file()
    assert view.parent != album
    assert not (album / "cloud.png").exists()
    assert {p.name for p in album.iterdir()} == before


def _attach(root: Path, name: str = "工况.xlsx") -> Path:
    folder = root / "3.测试组" / leg_test_dir_key(LEG, TEST) / "数据表附件"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"xlsx-bytes")
    return path


def test_resolve_data_table_path_remote_only_and_local_wins(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    cloud = _attach(remote, "cloud.xlsx")
    both_remote = _attach(remote, "both.xlsx")
    both_local = _attach(local, "both.xlsx")
    both_local.write_bytes(b"local-xlsx")

    cloud_rel = cloud.relative_to(remote).as_posix()
    both_rel = both_local.relative_to(local).as_posix()

    assert resolve_data_table_path(local, remote, cloud_rel) == cloud
    assert resolve_data_table_path(local, remote, both_rel) == both_local
    assert resolve_data_table_path(local, remote, both_rel) != both_remote
    assert resolve_data_table_path(local, None, cloud_rel) is None


def test_list_merged_attachment_refs_unions_local_and_remote(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    _attach(remote, "cloud.xlsx")
    _attach(local, "local.xlsx")
    _attach(remote, "both.xlsx")
    _attach(local, "both.xlsx")

    cloud = _attach(remote, "cloud.xlsx")
    refs = list_merged_attachment_refs(local, remote, LEG, TEST)
    names = {Path(r.relative_path).name for r in refs}
    assert names == {"cloud.xlsx", "local.xlsx", "both.xlsx"}
    cloud_ref = next(r for r in refs if Path(r.relative_path).name == "cloud.xlsx")
    assert resolve_data_table_path(local, remote, cloud_ref.relative_path) == cloud
