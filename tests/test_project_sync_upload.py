"""Project sync: incremental upload, verify, purge local large files."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.io.project_mirror import STRUCTURE_MIRROR_MAX_FILE_BYTES
from src.io.project_sync import (
    incremental_upload,
    purge_verified_uploads,
    sync_project_to_remote,
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


def test_incremental_upload_copies_new_files_to_remote(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    remote.mkdir()
    src = _png(_album(local) / "new.png", "green")
    spare = _album(local).parent / "备用"
    spare.mkdir(parents=True, exist_ok=True)
    _png(spare / "gone.png", "blue")
    (_album(local).parent / "数据表附件").mkdir(parents=True, exist_ok=True)
    ( _album(local).parent / "数据表附件" / "table.xlsx").write_bytes(b"xlsx-bytes")

    report = incremental_upload(local, remote)

    assert report.ok_paths
    assert (remote / src.relative_to(local)).is_file()
    assert (remote / "3.测试组" / leg_test_dir_key(LEG, TEST) / "备用" / "gone.png").is_file()
    assert (remote / "3.测试组" / leg_test_dir_key(LEG, TEST) / "数据表附件" / "table.xlsx").is_file()
    assert src.is_file()  # upload alone does not purge


def test_purge_verified_deletes_local_large_keeps_dirs(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    photo = _png(_album(local) / "shot.png")
    rel = photo.relative_to(local).as_posix()
    remote_photo = remote / rel
    remote_photo.parent.mkdir(parents=True, exist_ok=True)
    remote_photo.write_bytes(photo.read_bytes())

    light = _album(local, "试验前") / "note.txt"
    light.write_text("keep-local-light", encoding="utf-8")
    (remote / light.relative_to(local)).parent.mkdir(parents=True, exist_ok=True)
    (remote / light.relative_to(local)).write_text("keep-local-light", encoding="utf-8")

    purged = purge_verified_uploads(local, remote, [rel, light.relative_to(local).as_posix()])

    assert rel in purged
    assert not photo.exists()
    assert _album(local).is_dir()
    assert light.is_file()  # light non-xlsx text not purged


def test_purge_skips_when_remote_mismatch(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    photo = _png(_album(local) / "shot.png", "red")
    rel = photo.relative_to(local).as_posix()
    remote_photo = remote / rel
    remote_photo.parent.mkdir(parents=True, exist_ok=True)
    remote_photo.write_bytes(b"different-size-content")

    purged = purge_verified_uploads(local, remote, [rel])
    assert purged == []
    assert photo.is_file()


def test_sync_upload_then_purge_and_upload_failure_keeps_local(tmp_path: Path, monkeypatch):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    remote.mkdir()
    photo = _png(_album(local) / "shot.png")
    album = _album(local)

    report = sync_project_to_remote(local, remote)
    assert photo.relative_to(local).as_posix() in report.purged
    assert not photo.exists()
    assert album.is_dir()
    assert (remote / photo.relative_to(local)).is_file()

    # failure path: remote not writable / missing
    photo2 = _png(_album(local) / "fail.png", "yellow")
    bad_remote = tmp_path / "missing-remote"
    failed = sync_project_to_remote(local, bad_remote)
    assert failed.failed
    assert photo2.is_file()
