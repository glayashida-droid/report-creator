"""Startup cover is visible before preload and closes when preload finishes."""

import sys
import time

from PySide6.QtGui import QResizeEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

from src.io.network_sources import SOURCE_CONFIGURED, ProbeResult
from src.ui.main_window import (
    MainWindow,
    StartupCover,
    _COVER_FINISH_MS,
    _STARTUP_COVER_LINE,
    startup_cover_line,
)


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_cover_opens_on_the_welcome_line():
    _app()
    cover = StartupCover()
    try:
        assert cover._bar._sliding
        assert cover._bar.value() == 0
        assert cover._label.text() == _STARTUP_COVER_LINE
        cover.show()
        QTest.qWait(80)
        assert cover.isVisible()
        assert cover._label.text() == _STARTUP_COVER_LINE
        assert cover._prep_done is False
        frame = cover.findChild(QFrame, "startupCoverFrame")
        assert frame is not None
        assert cover._bar._anim.state() == cover._bar._anim.State.Running
        started = cover._bar._beam.x()
        QTest.qWait(90)
        assert cover._bar._beam.x() > started
    finally:
        cover._finish()


def test_cover_greets_saved_tester_name():
    _app()
    cover = StartupCover(tester_name="展玮鸿")
    try:
        assert cover._label.text() == startup_cover_line("展玮鸿")
        assert cover._label.text() == "\U0001f469\U0001f3fc\u200d\U0001f9b0你好，展玮鸿，欢迎使用Report Creator"
    finally:
        cover._finish()


def test_cover_stays_open_until_prep_finishes():
    _app()
    cover = StartupCover()
    try:
        cover.show()
        QTest.qWait(60)
        assert cover.isVisible()
        cover.mark_prep_done()
        QApplication.processEvents()
        assert cover._prep_done
        assert cover.isVisible()
        assert not cover._bar._sliding
        assert cover._bar.value() == 1
        QTest.qWait(_COVER_FINISH_MS + 80)
        assert not cover.isVisible()
    finally:
        cover._finish()


def test_cover_uses_session_tester_name(monkeypatch):
    _app()
    monkeypatch.setattr("src.ui.main_window.default_tester_name", lambda: "展玮鸿")
    win = MainWindow()
    seen = []

    def on_shown():
        seen.append(win._startup_cover._label.text())
        win._imports_done = True
        win._catalog_settled = True
        win._maybe_release_cover()

    win._on_cover_shown = on_shown
    win._prompt_tester_name = lambda **_kwargs: None
    win.present_startup_cover()
    assert seen == [startup_cover_line("展玮鸿")]
    win.close()


def _hold_cover(win):
    cover = StartupCover()
    win._startup_cover = cover
    win._cover_waits_for_network = True
    win._imports_done = True
    win._catalog_settled = True
    return cover


def test_cover_stays_open_until_the_share_answers():
    _app()
    win = MainWindow()
    cover = _hold_cover(win)
    try:
        win._cover_network_deadline = time.monotonic() + 30
        win._maybe_release_cover()
        assert not cover._prep_done
        win._on_network_probe_done(
            ProbeResult(
                equipment_ok=False,
                standards_ok=False,
                templates_ok=False,
                equipment_path=None,
                standards_path=None,
                equipment_error="",
                standards_error="",
                templates_error="",
            )
        )
        assert not cover._prep_done
        assert not win.chk_standards_conn.isChecked()
    finally:
        win._cover_network_ready = True
        win._startup_cover = None
        cover._finish()
        win.close()


def test_cover_closes_once_the_share_is_mounted():
    _app()
    win = MainWindow()
    cover = _hold_cover(win)
    try:
        win._cover_network_deadline = time.monotonic() + 30
        win._on_network_probe_done(
            ProbeResult(
                equipment_ok=True,
                standards_ok=True,
                templates_ok=True,
                equipment_path="/Volumes/eq/list.xlsx",
                standards_path="/Volumes/std/标准库.xlsx",
                equipment_error="",
                standards_error="",
                templates_error="",
                equipment_source=SOURCE_CONFIGURED,
                standards_source=SOURCE_CONFIGURED,
                templates_source=SOURCE_CONFIGURED,
            )
        )
        assert cover._prep_done
        assert win.chk_equipment_conn.isChecked()
        assert win.chk_standards_conn.isChecked()
        assert win.chk_templates_conn.isChecked()
    finally:
        cover._finish()
        win.close()


def test_cover_closes_when_the_share_budget_runs_out():
    _app()
    win = MainWindow()
    cover = _hold_cover(win)
    try:
        win._cover_network_deadline = time.monotonic() - 1
        win._expire_cover_network_budget()
        assert cover._prep_done
        assert not win.chk_equipment_conn.isChecked()
    finally:
        cover._finish()
        win.close()


def test_cover_retries_the_probe_while_the_share_is_still_down():
    _app()
    win = MainWindow()
    cover = _hold_cover(win)
    called = []
    win._start_network_probe = lambda: called.append("probe")
    try:
        win._cover_network_deadline = time.monotonic() + 30
        win._retry_cover_probe()
        assert called == ["probe"]
        assert not cover._prep_done
        called.clear()
        win._cover_network_deadline = time.monotonic() - 1
        win._retry_cover_probe()
        assert called == []
        assert cover._prep_done
    finally:
        cover._finish()
        win.close()


def test_preload_starts_only_after_the_cover_is_visible():
    _app()
    win = MainWindow()
    seen = []

    def on_shown():
        seen.append(win._startup_cover.isVisible())
        win._imports_done = True
        win._catalog_settled = True
        win._maybe_release_cover()

    win._on_cover_shown = on_shown
    win._prompt_tester_name = lambda **_kwargs: None
    win.present_startup_cover()
    assert seen == [True]
    win.close()


def test_cover_sweep_keeps_running_through_a_resize():
    _app()
    cover = StartupCover()
    try:
        cover.show()
        QTest.qWait(80)
        assert cover._bar._sweep_started
        mark = cover._bar._anim.currentTime()
        assert mark > 0
        cover._bar.resizeEvent(QResizeEvent(cover._bar.size(), cover._bar.size()))
        assert cover._bar._anim.state() == cover._bar._anim.State.Running
        assert cover._bar._anim.currentTime() >= mark
    finally:
        cover._finish()


def test_catalog_payload_skips_row_expand_when_nothing_is_waiting():
    _app()
    import pandas as pd

    win = MainWindow()
    calls = []
    win.leg_graph.db_loader.peek_standards = lambda: calls.append("std") or []
    win.leg_graph.db_loader.peek_equipments = lambda: calls.append("eq") or []
    win._catalog_waiters = []
    try:
        win._on_catalog_payload(
            {
                "standards_frame": pd.DataFrame([{"标准号": "ABC"}]),
                "standard_images": {},
                "standards_mtime": 1,
                "standards_error": "",
                "equipments_frame": pd.DataFrame([{"设备编号": "E1"}]),
                "equipments_mtime": 1,
                "equipments_error": "",
            }
        )
        assert calls == []
        assert win._catalog_settled
        assert win.leg_graph.db_loader.standards_df.iloc[0]["标准号"] == "ABC"
        assert win.leg_graph.db_loader.equipments_df.iloc[0]["设备编号"] == "E1"
    finally:
        win.close()
