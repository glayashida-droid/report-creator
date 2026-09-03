"""End-to-end smoke for nightly backup + cloud photos (spec Further notes / US-30–32)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.io.project_assets import (
    download_photo_to_album,
    iter_merged_export_photos,
    list_merged_photos,
    move_photo_to_spare,
)
from src.io.project_sync import (
    load_json_from_remote,
    save_json_to_remote_then_local,
    sync_project_to_remote,
)
from src.io.test_photos import SPARE_ALBUM_NAME, test_dir_key as leg_test_dir_key
from src.models.project_state import ProjectState, TestLeg, TestNode

LEG = "Leg 1"
TEST = "振动"
ALBUM = "试验前"


def _album(root: Path, album: str = ALBUM) -> Path:
    path = root / "3.测试组" / leg_test_dir_key(LEG, TEST) / album
    path.mkdir(parents=True, exist_ok=True)
    return path


def _png(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 24), color).save(path, "PNG")
    return path


def _by_stem(photos):
    return {Path(p.relative_path).stem: p for p in photos}


def test_further_notes_two_day_cloud_local_cycle_and_export(tmp_path: Path):
    """Day1 upload+purge → Day2 cloud → download 4 → add 6–10 → sync → export all."""
    local = tmp_path / "local_a"
    remote = tmp_path / "remote"
    remote.mkdir()
    album = _album(local)
    for i in range(1, 6):
        _png(album / f"{i:03d}.png", "blue")

    day1 = sync_project_to_remote(local, remote)
    assert len(day1.purged) == 5
    assert not any((album / f"{i:03d}.png").exists() for i in range(1, 6))
    assert album.is_dir()

    # Day 2 reopen: 1–5 cloud-only
    merged = list_merged_photos(local, remote, LEG, TEST, ALBUM)
    by = _by_stem(merged)
    assert set(by) == {f"{i:03d}" for i in range(1, 6)}
    assert all(by[s].is_cloud_only for s in by)

    # Download 4; drop in 6–10
    rel4 = by["004"].relative_path
    download_photo_to_album(local, remote, rel4)
    for i in range(6, 11):
        _png(album / f"{i:03d}.png", "green")

    mid = _by_stem(list_merged_photos(local, remote, LEG, TEST, ALBUM))
    assert set(mid) == {f"{i:03d}" for i in range(1, 11)}
    cloud = {s for s, p in mid.items() if p.is_cloud_only}
    local_only = {s for s, p in mid.items() if not p.is_cloud_only}
    assert cloud == {"001", "002", "003", "005"}
    assert local_only == {"004", "006", "007", "008", "009", "010"}

    day2 = sync_project_to_remote(local, remote)
    assert set(Path(r).stem for r in day2.purged) == local_only
    assert not any((album / f"{i:03d}.png").exists() for i in range(1, 11))

    temps: list[Path] = []
    exported = iter_merged_export_photos(
        local, remote, LEG, TEST, order=[ALBUM], temps=temps
    )
    assert [e.stem for e in exported] == [f"{i:03d}" for i in range(1, 11)]
    assert all(e.path.is_file() for e in exported)
    for t in temps:
        t.unlink(missing_ok=True)

    # Spare stays out of formal merge + export
    cloud_rel = mid["001"].relative_path
    download_photo_to_album(local, remote, cloud_rel)
    move_photo_to_spare(local, remote, cloud_rel)
    after = {
        Path(p.relative_path).stem
        for p in list_merged_photos(local, remote, LEG, TEST, ALBUM)
    }
    assert "001" not in after
    assert (_album(local).parent / SPARE_ALBUM_NAME / "001.png").is_file()
    temps2: list[Path] = []
    stems = [
        e.stem
        for e in iter_merged_export_photos(
            local, remote, LEG, TEST, order=[ALBUM], temps=temps2
        )
    ]
    assert "001" not in stems
    for t in temps2:
        t.unlink(missing_ok=True)


def test_us30_json_immediate_photos_lag_for_second_machine(tmp_path: Path):
    """US-30–32: B sees A's saved JSON schedule; local-only photos lag until sync."""
    remote = tmp_path / "remote"
    local_a = tmp_path / "local_a"
    local_b = tmp_path / "local_b"
    remote.mkdir()
    local_a.mkdir()
    local_b.mkdir()

    state = ProjectState(
        project_id="A22606909401",
        sample_name="排期可见",
        source_path=str(remote),
        project_path=str(local_a),
    )
    state.legs.append(
        TestLeg(leg_id="L1", leg_name=LEG, nodes=[TestNode(test_name=TEST)])
    )
    save_json_to_remote_then_local(state, local_a, remote)

    # A drops a daytime photo — not yet on remote
    _png(_album(local_a) / "day.png", "orange")
    assert not (_album(remote) / "day.png").exists()

    # B loads from remote JSON only
    loaded = load_json_from_remote(remote)
    assert loaded is not None
    assert loaded.sample_name == "排期可见"
    assert loaded.legs[0].nodes[0].test_name == TEST

    # B's merge view: no day.png until A syncs
    b_view = list_merged_photos(local_b, remote, LEG, TEST, ALBUM)
    assert "day" not in {Path(p.relative_path).stem for p in b_view}

    sync_project_to_remote(local_a, remote)
    b_after = _by_stem(list_merged_photos(local_b, remote, LEG, TEST, ALBUM))
    assert "day" in b_after
    assert b_after["day"].is_cloud_only is True
