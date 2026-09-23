import sys
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QCheckBox

from src.io.network_sources import (
    SOURCE_CONFIGURED,
    SOURCE_FALLBACK,
    SOURCE_MIXED,
    ConnectionCheckConfig,
    DirectorySource,
    EquipmentListSource,
    NetworkSourcesConfig,
    ProbeResult,
    StandardsLibrarySource,
)
from src.io.project_board import (
    resolve_openable_project_folders,
    resolve_project_folder_to_open,
)
from src.ui.main_window import (
    ConnectionStatusCheck,
    MainWindow,
    _apply_connection_status,
    _is_network_connection,
    _templates_are_network,
)
from src.ui.theme import CYAN, apply_cyberpunk_theme, question_pixmap


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    apply_cyberpunk_theme(app)
    return app


def _smb_config():
    return NetworkSourcesConfig(
        equipment_list=EquipmentListSource(
            directory="smb://host/eq", file_prefix="01-设备清单"
        ),
        standards_library=StandardsLibrarySource(file="smb://host/std.xlsx"),
        leg_templates=DirectorySource(directory="smb://host/leg"),
        report_templates=DirectorySource(directory="smb://host/report"),
        data_tables=DirectorySource(directory="smb://host/data"),
        original_data_sheet=DirectorySource(directory="smb://host/original"),
        connection_check=ConnectionCheckConfig(),
    )


def _probe(**kwargs):
    values = dict(
        equipment_ok=False,
        standards_ok=False,
        templates_ok=False,
        equipment_path=None,
        standards_path=None,
        equipment_error="",
        standards_error="",
        templates_error="",
    )
    values.update(kwargs)
    return ProbeResult(**values)


def test_is_network_connection_labels():
    assert _is_network_connection(SOURCE_CONFIGURED, "smb://host/share") is True
    assert _is_network_connection(SOURCE_FALLBACK, "smb://host/share") is False
    assert _is_network_connection(SOURCE_CONFIGURED, "/tmp/local") is False


def test_templates_are_network_requires_all_four():
    cfg = _smb_config()
    mixed = _probe(
        templates_ok=True,
        templates_source=SOURCE_MIXED,
        report_templates_source=SOURCE_CONFIGURED,
        leg_templates_source=SOURCE_FALLBACK,
        data_tables_source=SOURCE_CONFIGURED,
        original_data_sheet_source=SOURCE_CONFIGURED,
    )
    assert _templates_are_network(mixed, cfg) is False
    all_net = _probe(
        templates_ok=True,
        templates_source=SOURCE_CONFIGURED,
        report_templates_source=SOURCE_CONFIGURED,
        leg_templates_source=SOURCE_CONFIGURED,
        data_tables_source=SOURCE_CONFIGURED,
        original_data_sheet_source=SOURCE_CONFIGURED,
    )
    assert _templates_are_network(all_net, cfg) is True


def test_apply_connection_status_sets_checked_and_network_property():
    _app()
    chk = QCheckBox("x")
    chk.setObjectName("connectionStatus")
    _apply_connection_status(chk, ok=True, network=True)
    assert chk.isChecked()
    assert chk.property("network") == "true"
    _apply_connection_status(chk, ok=True, network=False)
    assert chk.isChecked()
    assert chk.property("network") == "false"
    _apply_connection_status(chk, ok=False, network=True)
    assert not chk.isChecked()
    assert chk.property("network") == "false"


def _render_indicator(chk: QCheckBox):
    from PySide6.QtGui import QColor, QImage

    from src.ui.theme import BG

    chk.setText("")
    chk.setEnabled(False)
    chk.setFixedSize(28, 22)
    chk.show()
    QApplication.processEvents()
    img = QImage(chk.size(), QImage.Format_ARGB32)
    img.fill(QColor(BG))
    chk.render(img)
    return img


def _has_approx_color(img, target_hex: str, *, tolerance: int = 70) -> bool:
    from PySide6.QtGui import QColor

    target = QColor(target_hex)
    for y in range(img.height()):
        for x in range(img.width()):
            pixel = QColor(img.pixel(x, y))
            if (
                abs(pixel.red() - target.red()) <= tolerance
                and abs(pixel.green() - target.green()) <= tolerance
                and abs(pixel.blue() - target.blue()) <= tolerance
            ):
                return True
    return False


def test_connection_status_paints_check_when_connected():
    from src.ui.theme import CYAN, TEXT_DIM

    _app()
    chk = ConnectionStatusCheck("")
    chk.setObjectName("connectionStatus")
    _apply_connection_status(chk, ok=False, network=False)
    empty = _render_indicator(chk)
    assert not _has_approx_color(empty, CYAN, tolerance=50)

    _apply_connection_status(chk, ok=True, network=True)
    connected = _render_indicator(chk)
    assert _has_approx_color(connected, CYAN)

    _apply_connection_status(chk, ok=True, network=False)
    local = _render_indicator(chk)
    assert _has_approx_color(local, TEXT_DIM)
    chk.close()


def test_probe_highlights_network_and_keeps_local_gray():
    _app()
    win = MainWindow()
    win._network_config = _smb_config()
    win._on_network_probe_done(
        _probe(
            equipment_ok=True,
            standards_ok=True,
            templates_ok=True,
            equipment_source=SOURCE_CONFIGURED,
            standards_source=SOURCE_FALLBACK,
            templates_source=SOURCE_CONFIGURED,
            report_templates_source=SOURCE_CONFIGURED,
            leg_templates_source=SOURCE_CONFIGURED,
            data_tables_source=SOURCE_CONFIGURED,
            original_data_sheet_source=SOURCE_CONFIGURED,
        )
    )
    assert win.chk_equipment_conn.isChecked()
    assert win.chk_equipment_conn.property("network") == "true"
    assert win.chk_standards_conn.isChecked()
    assert win.chk_standards_conn.property("network") == "false"
    assert win.chk_templates_conn.isChecked()
    assert win.chk_templates_conn.property("network") == "true"


def test_probe_unchecks_when_disconnected():
    _app()
    win = MainWindow()
    win._network_config = _smb_config()
    win._on_network_probe_done(_probe())
    assert not win.chk_equipment_conn.isChecked()
    assert win.chk_equipment_conn.property("network") == "false"
    assert not win.chk_standards_conn.isChecked()
    assert not win.chk_templates_conn.isChecked()


def test_mirror_ready_stays_local_gray(tmp_path: Path):
    _app()
    win = MainWindow()
    win._local_path = tmp_path
    win._set_mirror_status("", kind="ok")
    assert win.chk_mirror_conn.isChecked()
    assert win.chk_mirror_conn.property("network") == "false"
    win._set_mirror_status("未就绪", kind="dim")
    assert not win.chk_mirror_conn.isChecked()
    assert win.chk_mirror_conn.property("network") == "false"


def test_main_window_does_not_probe_until_shown():
    _app()
    win = MainWindow()
    assert win._network_probe_worker is None
    assert not win._connection_timer.isActive()
    win.close()


def test_main_window_mounts_then_probes_after_first_show():
    _app()
    order = []
    win = MainWindow()
    win._prompt_tester_name = lambda **_kwargs: True
    win._start_network_probe = lambda: order.append("probe")
    with patch(
        "src.ui.main_window.attempt_mount_network_shares",
        lambda _cfg: order.append("mount"),
    ):
        win.show()
        app = QApplication.instance()
        app.processEvents()
        app.processEvents()
    assert order == ["mount", "probe"]
    assert win._connection_timer.isActive()
    win.close()


def test_resolve_project_folder_prefers_reachable_remote(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    path, kind = resolve_project_folder_to_open(remote, local)
    assert kind == "remote"
    assert path == remote


def test_resolve_project_folder_falls_back_to_local(tmp_path: Path):
    remote = tmp_path / "missing-remote"
    local = tmp_path / "local"
    local.mkdir()
    path, kind = resolve_project_folder_to_open(remote, local)
    assert kind == "disconnected"
    assert path == local


def test_resolve_project_folder_local_only_when_remote_is_local(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    path, kind = resolve_project_folder_to_open(local, local)
    assert kind == "local"
    assert path == local


def test_resolve_project_folder_local_only_when_remote_missing(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    path, kind = resolve_project_folder_to_open(None, local)
    assert kind == "local"
    assert path == local


def test_resolve_project_folder_uses_normalized_unc(tmp_path: Path):
    remote = tmp_path / "share" / "proj"
    local = tmp_path / "local"
    remote.mkdir(parents=True)
    local.mkdir()
    with patch(
        "src.io.project_board.normalize_config_path",
        return_value=str(remote),
    ):
        path, kind = resolve_project_folder_to_open(
            Path(r"\\10.10.31.8\share\proj"), local
        )
    assert kind == "remote"
    assert path == remote


def test_resolve_project_folder_none_when_both_missing(tmp_path: Path):
    path, kind = resolve_project_folder_to_open(
        tmp_path / "no-remote", tmp_path / "no-local"
    )
    assert kind == "none"
    assert path is None


def test_resolve_openable_folders_returns_both(tmp_path: Path):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    remote_dir, local_dir = resolve_openable_project_folders(remote, local)
    assert remote_dir == remote
    assert local_dir == local


def test_resolve_openable_folders_omits_unreachable_remote(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    remote_dir, local_dir = resolve_openable_project_folders(
        tmp_path / "missing-remote", local
    )
    assert remote_dir is None
    assert local_dir == local


def test_resolve_openable_folders_treats_same_dir_as_local_only(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    remote_dir, local_dir = resolve_openable_project_folders(local, local)
    assert remote_dir is None
    assert local_dir == local


def test_open_button_visible_when_remote_ready_before_mirror(tmp_path: Path):
    _app()
    remote = tmp_path / "remote"
    remote.mkdir()
    win = MainWindow()
    win._source_path = remote
    win.state.source_path = str(remote)
    win._local_path = tmp_path / "local"
    win._set_mirror_status("镜像中...", kind="dim")
    assert not win.btn_open_local.isHidden()
    assert win.btn_open_local.toolTip() == "选择打开本地或公盘文件夹"
    win.close()


def test_open_button_tooltip_local_only(tmp_path: Path):
    _app()
    local = tmp_path / "local"
    local.mkdir()
    win = MainWindow()
    win._source_path = local
    win.state.source_path = ""
    win._local_path = local
    win._refresh_open_folder_button()
    assert not win.btn_open_local.isHidden()
    assert win.btn_open_local.toolTip() == "选择打开本地或公盘文件夹"
    win.close()


def test_open_button_tooltip_when_remote_disconnected(tmp_path: Path):
    _app()
    local = tmp_path / "local"
    local.mkdir()
    win = MainWindow()
    win._source_path = tmp_path / "offline-remote"
    win.state.source_path = str(tmp_path / "offline-remote")
    win._local_path = local
    win._refresh_open_folder_button()
    assert not win.btn_open_local.isHidden()
    assert win.btn_open_local.toolTip() == "选择打开本地或公盘文件夹"
    win.close()


def test_open_button_hidden_until_a_folder_exists():
    _app()
    win = MainWindow()
    win._set_mirror_status("尚未加载项目", kind="dim")
    assert win.btn_open_local.isHidden()
    win.close()


def test_open_project_folder_lets_user_pick_remote(tmp_path: Path):
    _app()
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    win = MainWindow()
    win._source_path = remote
    win.state.source_path = str(remote)
    win._local_path = local
    with patch.object(win, "_choose_open_folder_kind", return_value="remote") as mock_choose:
        with patch("src.ui.main_window._open_in_file_manager") as mock_open:
            win._open_project_folder()
    mock_choose.assert_called_once_with(local_available=True, remote_available=True)
    mock_open.assert_called_once_with(remote)
    win.close()


def test_open_project_folder_lets_user_pick_local(tmp_path: Path):
    _app()
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    win = MainWindow()
    win._source_path = remote
    win.state.source_path = str(remote)
    win._local_path = local
    with patch.object(win, "_choose_open_folder_kind", return_value="local"):
        with patch("src.ui.main_window._open_in_file_manager") as mock_open:
            win._open_project_folder()
    mock_open.assert_called_once_with(local)
    win.close()


def test_open_project_folder_cancel_does_not_open(tmp_path: Path):
    _app()
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    remote.mkdir()
    local.mkdir()
    win = MainWindow()
    win._source_path = remote
    win.state.source_path = str(remote)
    win._local_path = local
    with patch.object(win, "_choose_open_folder_kind", return_value=None):
        with patch("src.ui.main_window._open_in_file_manager") as mock_open:
            win._open_project_folder()
    mock_open.assert_not_called()
    win.close()


def test_open_project_folder_disconnected_opens_local_when_chosen(tmp_path: Path):
    _app()
    local = tmp_path / "local"
    local.mkdir()
    win = MainWindow()
    win._source_path = tmp_path / "offline-remote"
    win.state.source_path = str(tmp_path / "offline-remote")
    win._local_path = local
    with patch.object(win, "_choose_open_folder_kind", return_value="local") as mock_choose:
        with patch("src.ui.main_window._open_in_file_manager") as mock_open:
            win._open_project_folder()
    mock_choose.assert_called_once_with(local_available=True, remote_available=False)
    mock_open.assert_called_once_with(local)
    win.close()


def test_open_project_folder_local_only_when_chosen(tmp_path: Path):
    _app()
    local = tmp_path / "local"
    local.mkdir()
    win = MainWindow()
    win._source_path = local
    win.state.source_path = ""
    win._local_path = local
    with patch.object(win, "_choose_open_folder_kind", return_value="local") as mock_choose:
        with patch("src.ui.main_window._open_in_file_manager") as mock_open:
            win._open_project_folder()
    mock_choose.assert_called_once_with(local_available=True, remote_available=False)
    mock_open.assert_called_once_with(local)
    win.close()


def test_open_project_folder_opens_normalized_unc_remote(tmp_path: Path):
    _app()
    remote = tmp_path / "share" / "proj"
    local = tmp_path / "local"
    remote.mkdir(parents=True)
    local.mkdir()
    win = MainWindow()
    win._source_path = Path(r"\\10.10.31.8\share\proj")
    win.state.source_path = r"\\10.10.31.8\share\proj"
    win._local_path = local
    with patch(
        "src.io.project_board.normalize_config_path",
        return_value=str(remote),
    ), patch.object(win, "_choose_open_folder_kind", return_value="remote"), patch(
        "src.ui.main_window._open_in_file_manager"
    ) as mock_open:
        win._open_project_folder()
    mock_open.assert_called_once_with(remote)
    win.close()


def _cyan_vs_dark(pm):
    from PySide6.QtGui import QColor

    img = pm.toImage()
    assert not img.isNull()
    target = QColor(CYAN)
    cyans = 0
    darks = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            if c.alpha() < 40:
                continue
            if (
                abs(c.red() - target.red()) < 80
                and abs(c.green() - target.green()) < 80
                and abs(c.blue() - target.blue()) < 80
            ):
                cyans += 1
            if c.red() < 50 and c.green() < 50 and c.blue() < 50:
                darks += 1
    return cyans, darks


def test_question_pixmap_is_cyan_on_dark_background():
    _app()
    cyans, darks = _cyan_vs_dark(question_pixmap())
    assert cyans > 0
    assert cyans > darks


def test_question_message_box_uses_cyan_circle():
    from PySide6.QtWidgets import QMessageBox, QStyle

    app = _app()
    icon = app.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion)
    cyans, darks = _cyan_vs_dark(icon.pixmap(48, 48))
    assert cyans > 0
    assert cyans > darks

    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Question)
    cyans, darks = _cyan_vs_dark(box.iconPixmap())
    assert cyans > 0
    assert cyans > darks
