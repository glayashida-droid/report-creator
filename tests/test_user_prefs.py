"""Tests for user preferences persistence."""

from datetime import date

from src.io.user_prefs import (
    board_intranet_year,
    default_tester_name,
    load_user_prefs,
    nightly_sync_all_projects,
    nightly_sync_enabled,
    nightly_sync_time,
    save_board_intranet_year,
    save_default_tester_name,
    save_nightly_sync_prefs,
)


def test_default_tester_name_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.io.user_prefs.default_data_root", lambda: tmp_path)
    assert default_tester_name() == ""
    save_default_tester_name("黄佳林")
    assert default_tester_name() == "黄佳林"
    prefs = load_user_prefs()
    assert prefs["default_tester_name"] == "黄佳林"


def test_board_intranet_year_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.io.user_prefs.default_data_root", lambda: tmp_path)
    assert board_intranet_year() == date.today().year
    save_board_intranet_year(2027)
    assert board_intranet_year() == 2027
    save_board_intranet_year(1999)
    assert board_intranet_year() == 2027
    save_default_tester_name("黄佳林")
    assert load_user_prefs()["default_tester_name"] == "黄佳林"
    assert load_user_prefs()["board_intranet_year"] == 2027


def test_nightly_sync_prefs_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.io.user_prefs.default_data_root", lambda: tmp_path)
    assert nightly_sync_enabled() is False
    assert nightly_sync_time() == "22:30"
    assert nightly_sync_all_projects() is True
    save_nightly_sync_prefs(enabled=True, time_hhmm="21:05", all_projects=False)
    assert nightly_sync_enabled() is True
    assert nightly_sync_time() == "21:05"
    assert nightly_sync_all_projects() is False
    save_nightly_sync_prefs(enabled=False, time_hhmm="99:99", all_projects=True)
    assert nightly_sync_time() == "22:30"
