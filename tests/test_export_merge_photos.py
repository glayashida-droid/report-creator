"""Export merge view: remote-only photos embed without polluting albums."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.io.project_assets import iter_merged_export_photos
from src.io.test_photos import SPARE_ALBUM_NAME, test_dir_key as leg_test_dir_key

LEG = "Leg 1"
TEST = "振动"


def _album(root: Path, album: str = "试验前") -> Path:
    path = root / "3.测试组" / leg_test_dir_key(LEG, TEST) / album
    path.mkdir(parents=True, exist_ok=True)
    return path


def _png(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 48), color).save(path, "PNG")
    return path


def test_export_includes_remote_only_excludes_spare_no_album_pollution(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    cloud = _png(_album(remote) / "cloud.png", "blue")
    spare = _album(remote).parent / SPARE_ALBUM_NAME
    spare.mkdir(parents=True, exist_ok=True)
    _png(spare / "deleted.png", "black")
    local_album = _album(local)
    before = {p.name for p in local_album.iterdir()}

    temps: list[Path] = []
    exported = iter_merged_export_photos(
        local, remote, LEG, TEST, order=["试验前"], temps=temps
    )
    names = [item.stem for item in exported]
    assert names == ["cloud"]
    assert all(item.path.is_file() for item in exported)
    assert temps
    assert all(t.is_file() for t in temps)
    assert "deleted" not in names

    # Formal local album still empty — temps are outside album
    assert {p.name for p in local_album.iterdir()} == before
    assert not (local_album / "cloud.png").exists()
    for item in exported:
        assert item.path.parent != local_album

    for t in temps:
        t.unlink(missing_ok=True)
