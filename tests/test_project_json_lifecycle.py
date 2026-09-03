"""JSON lifecycle seam: remote authority, local cache, save order."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.io.project_sync import (
    RemoteJsonError,
    is_pending_remote_json,
    is_remote_json_newer,
    load_json_from_remote,
    pending_baseline_mtime,
    remote_diverged_from_pending,
    save_json_local_pending_remote,
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


def test_save_json_local_pending_records_baseline_and_writes_local(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    remote_json = remote / "project_state.json"
    local_json = local / "project_state.json"
    remote_json.write_text('{"sample_name":"旧公盘"}', encoding="utf-8")
    local_json.write_text('{"sample_name":"旧缓存"}', encoding="utf-8")
    os.utime(remote_json, (time.time() - 20, time.time() - 20))
    os.utime(local_json, (time.time() - 20, time.time() - 20))
    baseline_before = remote_json.stat().st_mtime

    save_json_local_pending_remote(_state(sample="离线排期"), local, remote)

    local_data = json.loads(local_json.read_text(encoding="utf-8"))
    assert local_data["sample_name"] == "离线排期"
    assert remote_json.read_text(encoding="utf-8") == '{"sample_name":"旧公盘"}'
    assert is_pending_remote_json(local) is True
    assert pending_baseline_mtime(local) == pytest.approx(baseline_before)
    assert remote_diverged_from_pending(local, remote) is False


def test_remote_diverged_from_pending_when_remote_mtime_moves(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    remote_json = remote / "project_state.json"
    (local / "project_state.json").write_text('{"sample_name":"旧"}', encoding="utf-8")
    remote_json.write_text('{"sample_name":"旧公盘"}', encoding="utf-8")
    os.utime(remote_json, (time.time() - 30, time.time() - 30))

    save_json_local_pending_remote(_state(sample="本地待同步"), local, remote)
    assert remote_diverged_from_pending(local, remote) is False

    remote_json.write_text('{"sample_name":"同事写入"}', encoding="utf-8")
    os.utime(remote_json, (time.time(), time.time()))
    assert remote_diverged_from_pending(local, remote) is True


def test_save_json_to_remote_clears_pending_marker(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    save_json_local_pending_remote(_state(sample="待传"), local, None)
    assert is_pending_remote_json(local) is True

    save_json_to_remote_then_local(_state(sample="已同步"), local, remote)
    assert is_pending_remote_json(local) is False
    data = json.loads((remote / "project_state.json").read_text(encoding="utf-8"))
    assert data["sample_name"] == "已同步"


def test_preserve_baseline_keeps_conflict_after_later_local_save(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    remote_json = remote / "project_state.json"
    (local / "project_state.json").write_text('{"sample_name":"旧"}', encoding="utf-8")
    remote_json.write_text('{"sample_name":"旧公盘"}', encoding="utf-8")
    os.utime(remote_json, (time.time() - 30, time.time() - 30))
    save_json_local_pending_remote(_state(sample="本地一"), local, remote)

    remote_json.write_text('{"sample_name":"同事"}', encoding="utf-8")
    os.utime(remote_json, (time.time(), time.time()))
    save_json_local_pending_remote(
        _state(sample="本地二"), local, remote, preserve_baseline=True
    )
    assert remote_diverged_from_pending(local, remote) is True
    local_data = json.loads((local / "project_state.json").read_text(encoding="utf-8"))
    assert local_data["sample_name"] == "本地二"


def test_main_window_save_writes_local_pending_when_remote_unwritable(tmp_path: Path):
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
        assert win.save_state(show_success=False) is True

    local_data = json.loads((local / "project_state.json").read_text(encoding="utf-8"))
    assert local_data["sample_name"] == "新"
    assert win._is_dirty is False
    assert is_pending_remote_json(local) is True
    win._refresh_remote_json_status()
    tip = win.chk_mirror_conn.toolTip()
    assert "公盘 不可达" in tip
    assert "待同步" in tip


def test_main_window_save_falls_back_local_when_remote_write_fails(tmp_path: Path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QMessageBox

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    (remote / "project_state.json").write_text(
        '{"sample_name":"旧公盘"}', encoding="utf-8"
    )

    win = MainWindow()
    win.state = _state(sample="新")
    win.state.source_path = str(remote)
    win._source_path = remote
    win._local_path = local
    win._is_dirty = True

    with patch.object(win, "_sync_dates_to_state"), patch.object(
        QMessageBox, "warning", return_value=QMessageBox.Ok
    ), patch(
        "src.ui.main_window.save_json_to_remote_then_local",
        side_effect=RemoteJsonError("disk full"),
    ):
        assert win.save_state(show_success=False) is True

    local_data = json.loads((local / "project_state.json").read_text(encoding="utf-8"))
    assert local_data["sample_name"] == "新"
    assert json.loads((remote / "project_state.json").read_text(encoding="utf-8"))[
        "sample_name"
    ] == "旧公盘"
    assert is_pending_remote_json(local) is True
    assert win._is_dirty is False


def test_main_window_reconnect_flushes_pending_when_remote_unchanged(tmp_path: Path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QMessageBox

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    remote = tmp_path / "share" / "project"
    parked = tmp_path / "parked"
    local = tmp_path / "local"
    remote.mkdir(parents=True)
    local.mkdir()
    save_json_to_remote_then_local(_state(sample="旧公盘"), local, remote)
    remote_json = remote / "project_state.json"
    os.utime(remote_json, (time.time() - 30, time.time() - 30))
    os.utime(local / "project_state.json", (time.time() - 30, time.time() - 30))
    remote.rename(parked)

    win = MainWindow()
    win.state = _state(sample="离线改")
    win.state.source_path = str(remote)
    win._source_path = remote
    win._local_path = local
    win._is_dirty = True

    with patch.object(win, "_sync_dates_to_state"), patch.object(
        QMessageBox, "warning", return_value=QMessageBox.Ok
    ):
        assert win.save_state(show_success=False) is True
    assert is_pending_remote_json(local) is True

    parked.rename(remote)
    win._try_flush_pending_remote_json(interactive=False)

    assert is_pending_remote_json(local) is False
    remote_data = json.loads(remote_json.read_text(encoding="utf-8"))
    assert remote_data["sample_name"] == "离线改"


def test_main_window_reconnect_conflict_does_not_silent_overwrite(tmp_path: Path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QMessageBox

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    remote = tmp_path / "share" / "project"
    parked = tmp_path / "parked"
    local = tmp_path / "local"
    remote.mkdir(parents=True)
    local.mkdir()
    save_json_to_remote_then_local(_state(sample="旧公盘"), local, remote)
    remote.rename(parked)

    win = MainWindow()
    win.state = _state(sample="离线改")
    win.state.source_path = str(remote)
    win._source_path = remote
    win._local_path = local
    win._is_dirty = True

    with patch.object(win, "_sync_dates_to_state"), patch.object(
        QMessageBox, "warning", return_value=QMessageBox.Ok
    ):
        assert win.save_state(show_success=False) is True

    parked.rename(remote)
    remote_json = remote / "project_state.json"
    remote_json.write_text('{"sample_name":"同事"}', encoding="utf-8")
    os.utime(remote_json, (time.time(), time.time()))

    win._try_flush_pending_remote_json(interactive=False)

    assert is_pending_remote_json(local) is True
    assert json.loads(remote_json.read_text(encoding="utf-8"))["sample_name"] == "同事"

    with patch.object(win, "_ask_pending_json_conflict", return_value="local"):
        win._try_flush_pending_remote_json(interactive=True)

    assert is_pending_remote_json(local) is False
    assert json.loads(remote_json.read_text(encoding="utf-8"))["sample_name"] == "离线改"


def test_main_window_conflict_take_remote_reloads_and_clears_pending(tmp_path: Path):
    import sys
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QMessageBox

    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    remote = tmp_path / "share" / "project"
    parked = tmp_path / "parked"
    local = tmp_path / "local"
    remote.mkdir(parents=True)
    local.mkdir()
    save_json_to_remote_then_local(_state(sample="旧公盘"), local, remote)
    remote.rename(parked)

    win = MainWindow()
    win.state = _state(sample="离线改")
    win.state.source_path = str(remote)
    win._source_path = remote
    win._local_path = local
    win._is_dirty = True

    with patch.object(win, "_sync_dates_to_state"), patch.object(
        QMessageBox, "warning", return_value=QMessageBox.Ok
    ):
        assert win.save_state(show_success=False) is True

    parked.rename(remote)
    colleague = _state(sample="同事公盘")
    colleague.source_path = str(remote)
    colleague.save_to_file(str(remote / "project_state.json"))
    os.utime(remote / "project_state.json", (time.time(), time.time()))

    with patch.object(win, "_ask_pending_json_conflict", return_value="remote"), patch.object(
        win, "_apply_state_to_ui"
    ), patch.object(win, "_mount_tester_on_project"):
        win._try_flush_pending_remote_json(interactive=True)

    assert is_pending_remote_json(local) is False
    assert win.state.sample_name == "同事公盘"
    assert win._is_dirty is False


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
