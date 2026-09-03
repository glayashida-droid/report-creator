"""JSON lifecycle seam: remote authority, local cache, save order."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.io.project_sync import (
    RemoteJsonError,
    is_remote_json_newer,
    load_json_from_remote,
    save_json_to_remote_then_local,
)
from src.models.project_state import ProjectState, TestLeg, TestNode


def _state(pid: str = "A22600000001", sample: str = "控制器") -> ProjectState:
    state = ProjectState(project_id=pid, sample_name=sample, source_path="/remote")
    state.legs.append(
        TestLeg(leg_id="L1", leg_name="Leg 1", nodes=[TestNode(test_name="振动")])
    )
    return state


def test_save_json_writes_remote_before_local(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    state = _state(sample="宇通控制器")

    save_json_to_remote_then_local(state, local, remote)

    remote_json = remote / "project_state.json"
    local_json = local / "project_state.json"
    assert remote_json.is_file()
    assert local_json.is_file()
    remote_data = json.loads(remote_json.read_text(encoding="utf-8"))
    local_data = json.loads(local_json.read_text(encoding="utf-8"))
    assert remote_data["sample_name"] == "宇通控制器"
    assert local_data == remote_data


def test_save_json_remote_failure_leaves_local_untouched(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    local.mkdir()
    # remote path is a plain file → cannot place project_state.json under it
    remote.write_text("not-a-dir", encoding="utf-8")
    local_json = local / "project_state.json"
    local_json.write_text('{"sample_name":"旧缓存"}', encoding="utf-8")

    state = _state(sample="新排期")
    with pytest.raises(RemoteJsonError):
        save_json_to_remote_then_local(state, local, remote)

    assert local_json.read_text(encoding="utf-8") == '{"sample_name":"旧缓存"}'
    assert not (tmp_path / "remote" / "project_state.json").exists()


def test_load_json_from_remote(tmp_path: Path):
    remote = tmp_path / "remote"
    remote.mkdir()
    state = _state(sample="公盘排期")
    state.save_to_file(str(remote / "project_state.json"))

    loaded = load_json_from_remote(remote)
    assert loaded is not None
    assert loaded.sample_name == "公盘排期"
    assert loaded.legs[0].nodes[0].test_name == "振动"


def test_load_json_from_remote_missing_returns_none(tmp_path: Path):
    remote = tmp_path / "remote"
    remote.mkdir()
    assert load_json_from_remote(remote) is None


def test_is_remote_json_newer_when_remote_mtime_ahead(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    local_json = local / "project_state.json"
    remote_json = remote / "project_state.json"
    local_json.write_text('{"sample_name":"本地"}', encoding="utf-8")
    time.sleep(0.05)
    remote_json.write_text('{"sample_name":"公盘"}', encoding="utf-8")
    # Ensure remote mtime is strictly newer even on coarse FS clocks
    os.utime(local_json, (time.time() - 10, time.time() - 10))
    os.utime(remote_json, (time.time(), time.time()))

    assert is_remote_json_newer(local, remote) is True


def test_is_remote_json_newer_false_when_local_ahead(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    remote_json = remote / "project_state.json"
    local_json = local / "project_state.json"
    remote_json.write_text('{"sample_name":"公盘"}', encoding="utf-8")
    local_json.write_text('{"sample_name":"本地"}', encoding="utf-8")
    os.utime(remote_json, (time.time() - 10, time.time() - 10))
    os.utime(local_json, (time.time(), time.time()))

    assert is_remote_json_newer(local, remote) is False


def test_is_remote_json_newer_false_when_remote_missing(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    (local / "project_state.json").write_text("{}", encoding="utf-8")
    assert is_remote_json_newer(local, remote) is False


def test_main_window_save_writes_remote_then_local(tmp_path: Path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()

    win = MainWindow()
    win.state = _state(sample="保存上公盘")
    win.state.source_path = str(remote)
    win._source_path = remote
    win._local_path = local
    win._is_dirty = True

    with patch.object(win, "_sync_dates_to_state"):
        assert win.save_state(show_success=False) is True

    remote_data = json.loads((remote / "project_state.json").read_text(encoding="utf-8"))
    local_data = json.loads((local / "project_state.json").read_text(encoding="utf-8"))
    assert remote_data["sample_name"] == "保存上公盘"
    assert local_data == remote_data
    assert win._is_dirty is False


def test_main_window_save_keeps_dirty_when_remote_unwritable(tmp_path: Path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QMessageBox

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    remote = tmp_path / "remote"
    local = tmp_path / "local"
    local.mkdir()
    remote.write_text("not-a-dir", encoding="utf-8")
    (local / "project_state.json").write_text('{"sample_name":"旧"}', encoding="utf-8")

    win = MainWindow()
    win.state = _state(sample="新")
    win.state.source_path = str(remote)
    win._source_path = remote
    win._local_path = local
    win._is_dirty = True

    with patch.object(win, "_sync_dates_to_state"), patch.object(
        QMessageBox, "warning", return_value=QMessageBox.Ok
    ):
        assert win.save_state(show_success=False) is False

    assert (local / "project_state.json").read_text(encoding="utf-8") == '{"sample_name":"旧"}'
    assert win._is_dirty is True
    win._refresh_remote_json_status()
    assert "公盘 不可达" in win.chk_mirror_conn.toolTip()


def test_main_window_remote_json_status_ok_when_source_reachable(tmp_path: Path):
    import sys

    from PySide6.QtWidgets import QApplication

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "project_state.json").write_text("{}", encoding="utf-8")

    win = MainWindow()
    win.state = _state()
    win.state.source_path = str(remote)
    win._source_path = remote
    win._refresh_remote_json_status()
    tip = win.chk_mirror_conn.toolTip()
    assert "公盘 可达" in tip
    assert "project_state.json" in tip
