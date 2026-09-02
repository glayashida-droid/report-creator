"""Project assets seam: merge local + remote photo views."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.io.project_assets import (
    list_merged_albums,
    list_merged_photos,
    resolve_photo_path,
    thumbnail_for_photo,
)
from src.io.test_photos import test_dir_key as leg_test_dir_key

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
