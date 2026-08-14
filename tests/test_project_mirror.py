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
    test_list_saved_projects()
    print("test_project_mirror: ok")
