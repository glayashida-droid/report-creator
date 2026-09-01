"""Tests for user preferences persistence."""

from src.io.user_prefs import default_tester_name, load_user_prefs, save_default_tester_name


def test_default_tester_name_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.io.user_prefs.default_data_root", lambda: tmp_path)
    assert default_tester_name() == ""
    save_default_tester_name("黄佳林")
    assert default_tester_name() == "黄佳林"
    prefs = load_user_prefs()
    assert prefs["default_tester_name"] == "黄佳林"
