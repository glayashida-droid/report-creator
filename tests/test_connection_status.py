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
from src.ui.main_window import (
    ConnectionStatusCheck,
    MainWindow,
    _apply_connection_status,
    _is_network_connection,
    _templates_are_network,
)
from src.ui.theme import apply_cyberpunk_theme


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


def test_templates_are_network_requires_all_three():
    cfg = _smb_config()
    mixed = _probe(
        templates_ok=True,
        templates_source=SOURCE_MIXED,
        report_templates_source=SOURCE_CONFIGURED,
        leg_templates_source=SOURCE_FALLBACK,
        data_tables_source=SOURCE_CONFIGURED,
    )
    assert _templates_are_network(mixed, cfg) is False
    all_net = _probe(
        templates_ok=True,
        templates_source=SOURCE_CONFIGURED,
        report_templates_source=SOURCE_CONFIGURED,
        leg_templates_source=SOURCE_CONFIGURED,
        data_tables_source=SOURCE_CONFIGURED,
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
