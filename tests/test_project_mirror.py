import json
import tempfile
from pathlib import Path

from src.io.project_mirror import incremental_copy, list_saved_projects
from src.models.project_state import ProjectState, TestLeg, TestNode


def test_incremental_copy_and_skip_junk():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dest = Path(tmp) / "dest"
        (src / "1.接样组").mkdir(parents=True)
        (src / "1.接样组" / "app.xlsx").write_bytes(b"excel")
        (src / "1.接样组" / ".DS_Store").write_bytes(b"junk")
        (src / "1.接样组" / "~$lock.xlsx").write_bytes(b"lock")
        (src / "project_state.json").write_text("from-source", encoding="utf-8")

        assert incremental_copy(src, dest) is True
        assert (dest / "1.接样组" / "app.xlsx").read_bytes() == b"excel"
        assert not (dest / "1.接样组" / ".DS_Store").exists()
        assert not (dest / "1.接样组" / "~$lock.xlsx").exists()
        assert not (dest / "project_state.json").exists()

        (dest / "project_state.json").write_text("keep-me", encoding="utf-8")
        (src / "1.接样组" / "app.xlsx").write_bytes(b"excel")
        assert incremental_copy(src, dest) is True
        assert (dest / "project_state.json").read_text(encoding="utf-8") == "keep-me"


def test_incremental_copy_can_cancel():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dest = Path(tmp) / "dest"
        src.mkdir()
        (src / "a.bin").write_bytes(b"aaa")
        cancelled = True
        assert incremental_copy(src, dest, cancelled=lambda: cancelled) is False


def test_structure_mirror_skips_images_keeps_dirs_copies_light_xlsx():
    """Structure mirror: album dirs exist, photos stay remote-only, light xlsx copies."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dest = Path(tmp) / "dest"
        album = src / "3.测试组" / "Leg1-振动" / "试验前"
        album.mkdir(parents=True)
        (album / "shot.jpg").write_bytes(b"\xff\xd8" + b"img" * 100)
        (album / "shot.PNG").write_bytes(b"png-bytes")
        app_dir = src / "1.接样组"
        app_dir.mkdir(parents=True)
        (app_dir / "A22600000001.xlsx").write_bytes(b"small-application")

        assert incremental_copy(src, dest) is True

        assert (dest / "3.测试组" / "Leg1-振动" / "试验前").is_dir()
        assert not (dest / "3.测试组" / "Leg1-振动" / "试验前" / "shot.jpg").exists()
        assert not (dest / "3.测试组" / "Leg1-振动" / "试验前" / "shot.PNG").exists()
        assert (dest / "1.接样组" / "A22600000001.xlsx").read_bytes() == b"small-application"


def test_structure_mirror_skips_files_over_size_threshold():
    from src.io.project_mirror import STRUCTURE_MIRROR_MAX_FILE_BYTES

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        dest = Path(tmp) / "dest"
        tables = src / "3.测试组" / "Leg1-振动" / "数据表附件"
        tables.mkdir(parents=True)
        (tables / "big.xlsx").write_bytes(b"x" * (STRUCTURE_MIRROR_MAX_FILE_BYTES + 1))
        (tables / "tiny.xlsx").write_bytes(b"tiny")

        assert incremental_copy(src, dest) is True

        assert (dest / "3.测试组" / "Leg1-振动" / "数据表附件").is_dir()
        assert not (dest / "3.测试组" / "Leg1-振动" / "数据表附件" / "big.xlsx").exists()
        assert (dest / "3.测试组" / "Leg1-振动" / "数据表附件" / "tiny.xlsx").read_bytes() == b"tiny"


def test_list_saved_projects():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        empty = root / "NOJSON"
        empty.mkdir()
        pid = "A2260542168101"
        state_dir = root / pid
        state = ProjectState(
            project_id=pid,
            applicant_name="宇通",
            sample_name="控制器",
        )
        state.legs.append(TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[TestNode(test_name="振动")]))
        state.save_to_file(str(state_dir / "project_state.json"))

        listed = list_saved_projects(root)
        assert len(listed) == 1
        assert listed[0].project_id == pid
        assert listed[0].applicant_name == "宇通"
        assert listed[0].sample_name == "控制器"

        loaded = ProjectState.load_from_file(str(listed[0].json_path))
        assert loaded.legs[0].nodes[0].test_name == "振动"
        assert json.loads(listed[0].json_path.read_text(encoding="utf-8"))["excluded_overview_keys"] == []


if __name__ == "__main__":
    test_incremental_copy_and_skip_junk()
    test_incremental_copy_can_cancel()
    test_structure_mirror_skips_images_keeps_dirs_copies_light_xlsx()
    test_structure_mirror_skips_files_over_size_threshold()
    test_list_saved_projects()
    print("test_project_mirror: ok")
