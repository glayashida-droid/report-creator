from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.io.usage_stats import (
    UsageTracker,
    aggregate_days,
    aggregate_weeks,
    load_tester_source,
    monday_of,
    publish_usage_csvs,
    safe_tester_stem,
    session_slices,
    usage_tracking_enabled,
)


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_overnight_open_splits_at_midnight():
    slices = session_slices(
        "s1",
        _dt("2026-09-15T08:00:00"),
        _dt("2026-09-16T10:00:00"),
        closed=False,
    )
    assert [(item.date, item.start, item.end, item.hours) for item in slices] == [
        ("2026-09-15", "08:00", "24:00", 16.0),
        ("2026-09-16", "00:00", "10:00", 10.0),
    ]


def test_overnight_to_midnight_is_sixteen_hours():
    slices = session_slices(
        "s1",
        _dt("2026-09-15T08:00:00"),
        _dt("2026-09-16T00:00:00"),
        closed=True,
    )
    assert len(slices) == 1
    assert slices[0].date == "2026-09-15"
    assert slices[0].start == "08:00"
    assert slices[0].end == "24:00"
    assert slices[0].hours == 16.0


def test_same_day_session_keeps_clock_times():
    slices = session_slices(
        "s1",
        _dt("2026-09-15T08:00:00"),
        _dt("2026-09-15T18:30:00"),
        closed=True,
    )
    assert slices[0].start == "08:00"
    assert slices[0].end == "18:30"
    assert slices[0].hours == 10.5


def test_week_starts_monday():
    assert monday_of(_dt("2026-09-15").date()).isoformat() == "2026-09-14"
    assert monday_of(_dt("2026-09-14").date()).isoformat() == "2026-09-14"
    assert monday_of(_dt("2026-09-20").date()).isoformat() == "2026-09-14"
    assert monday_of(_dt("2026-09-21").date()).isoformat() == "2026-09-21"


def test_tracker_flush_writes_person_and_summary_csvs(tmp_path: Path):
    remote = tmp_path / "usage"
    local = tmp_path / "local"
    tracker = UsageTracker(
        tester_name="展玮鸿",
        machine_id="mac-a",
        local_dir=local,
        remote_dir=remote,
    )
    tracker.start(_dt("2026-09-15T08:00:00"))
    tracker.record_report(_dt("2026-09-15T11:00:00"))
    tracker.record_original_record(_dt("2026-09-15T12:00:00"))
    tracker.tick(_dt("2026-09-16T18:30:00"))

    daily = _read_csv(remote / "展玮鸿_日.csv")
    assert daily[0]["日期"] == "2026-09-15"
    assert daily[0]["首次启动"] == "08:00"
    assert daily[0]["末次关闭"] == "24:00"
    assert daily[0]["时长小时"] == "16.00"
    assert daily[0]["报告数"] == "1"
    assert daily[0]["原始记录数"] == "1"
    assert daily[1]["日期"] == "2026-09-16"
    assert daily[1]["首次启动"] == "00:00"
    assert daily[1]["末次关闭"] == "18:30"
    assert daily[1]["时长小时"] == "18.50"
    assert daily[1]["报告数"] == "0"

    weekly = _read_csv(remote / "展玮鸿_周.csv")
    assert weekly[0]["周起始"] == "2026-09-14"
    assert weekly[0]["首次启动"] == "2026-09-15 08:00"
    assert weekly[0]["末次关闭"] == "2026-09-16 18:30"
    assert weekly[0]["时长小时"] == "34.50"
    assert weekly[0]["报告数"] == "1"
    assert weekly[0]["原始记录数"] == "1"

    summary = _read_csv(remote / "汇总_日.csv")
    assert summary[0]["展玮鸿_首次启动"] == "08:00"
    assert summary[0]["展玮鸿_报告数"] == "1"
    assert summary[0]["展玮鸿_原始记录数"] == "1"
    week_summary = _read_csv(remote / "汇总_周.csv")
    assert week_summary[0]["周起始"] == "2026-09-14"
    assert week_summary[0]["展玮鸿_时长小时"] == "34.50"


def test_two_sessions_same_day_sum_hours(tmp_path: Path):
    remote = tmp_path / "usage"
    tracker = UsageTracker(
        tester_name="黄佳林",
        machine_id="mac-a",
        local_dir=tmp_path / "local",
        remote_dir=remote,
    )
    tracker.start(_dt("2026-09-15T08:00:00"))
    tracker.close(_dt("2026-09-15T12:00:00"))
    tracker.start(_dt("2026-09-15T14:00:00"))
    tracker.close(_dt("2026-09-15T18:00:00"))

    daily = _read_csv(remote / "黄佳林_日.csv")
    assert daily[0]["首次启动"] == "08:00"
    assert daily[0]["末次关闭"] == "18:00"
    assert daily[0]["时长小时"] == "8.00"


def test_merge_two_machines_same_tester(tmp_path: Path):
    remote = tmp_path / "usage"
    first = UsageTracker(
        tester_name="展玮鸿",
        machine_id="mac-a",
        local_dir=tmp_path / "a",
        remote_dir=remote,
    )
    first.start(_dt("2026-09-15T08:00:00"))
    first.record_report(_dt("2026-09-15T09:00:00"))
    first.close(_dt("2026-09-15T12:00:00"))

    second = UsageTracker(
        tester_name="展玮鸿",
        machine_id="mac-b",
        local_dir=tmp_path / "b",
        remote_dir=remote,
    )
    second.start(_dt("2026-09-15T13:00:00"))
    second.record_original_record(_dt("2026-09-15T14:00:00"))
    second.close(_dt("2026-09-15T17:00:00"))

    daily = _read_csv(remote / "展玮鸿_日.csv")
    assert daily[0]["首次启动"] == "08:00"
    assert daily[0]["末次关闭"] == "17:00"
    assert daily[0]["时长小时"] == "8.00"
    assert daily[0]["报告数"] == "1"
    assert daily[0]["原始记录数"] == "1"


def test_summary_csv_uses_tester_columns(tmp_path: Path):
    remote = tmp_path / "usage"
    for name, machine, start, end in (
        ("展玮鸿", "a", "2026-09-15T08:00:00", "2026-09-15T10:00:00"),
        ("黄佳林", "b", "2026-09-15T09:00:00", "2026-09-15T12:00:00"),
    ):
        tracker = UsageTracker(
            tester_name=name,
            machine_id=machine,
            local_dir=tmp_path / machine,
            remote_dir=remote,
        )
        tracker.start(_dt(start))
        tracker.close(_dt(end))

    rows = _read_csv(remote / "汇总_日.csv")
    assert rows[0]["日期"] == "2026-09-15"
    assert rows[0]["展玮鸿_时长小时"] == "2.00"
    assert rows[0]["黄佳林_时长小时"] == "3.00"
    assert rows[0]["展玮鸿_首次启动"] == "08:00"
    assert rows[0]["黄佳林_首次启动"] == "09:00"


def test_local_pending_syncs_when_remote_appears(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "usage"
    tracker = UsageTracker(
        tester_name="展玮鸿",
        machine_id="mac-a",
        local_dir=local,
        remote_dir=None,
    )
    tracker.start(_dt("2026-09-15T08:00:00"))
    tracker.close(_dt("2026-09-15T10:00:00"))
    assert not remote.exists()
    assert load_tester_source(local, "展玮鸿", "mac-a") is not None

    tracker.remote_dir = remote
    tracker.tick(_dt("2026-09-15T10:05:00"))
    assert (remote / "展玮鸿_日.csv").is_file()
    assert _read_csv(remote / "展玮鸿_日.csv")[0]["时长小时"] == "2.00"


def test_rename_closes_old_tester_and_opens_new(tmp_path: Path):
    remote = tmp_path / "usage"
    tracker = UsageTracker(
        tester_name="旧名",
        machine_id="mac-a",
        local_dir=tmp_path / "local",
        remote_dir=remote,
    )
    tracker.start(_dt("2026-09-15T08:00:00"))
    tracker.rename_tester("新名", _dt("2026-09-15T10:00:00"))
    tracker.close(_dt("2026-09-15T12:00:00"))

    old_rows = _read_csv(remote / "旧名_日.csv")
    new_rows = _read_csv(remote / "新名_日.csv")
    assert old_rows[0]["时长小时"] == "2.00"
    assert old_rows[0]["末次关闭"] == "10:00"
    assert new_rows[0]["首次启动"] == "10:00"
    assert new_rows[0]["时长小时"] == "2.00"


def test_safe_tester_stem_strips_path_chars():
    assert safe_tester_stem("张三/李四") == "张三_李四"
    assert safe_tester_stem("  ") == "unknown"


def test_pytest_disables_silent_tracking_by_default():
    assert usage_tracking_enabled() is False


def test_aggregate_weeks_rolls_mon_sun():
    days = aggregate_days(
        session_slices(
            "s1",
            _dt("2026-09-14T22:00:00"),
            _dt("2026-09-15T02:00:00"),
            closed=True,
        ),
        [],
    )
    weeks = aggregate_weeks(days)
    assert list(weeks) == ["2026-09-14"]
    assert weeks["2026-09-14"].duration_hours == 4.0
    assert weeks["2026-09-14"].first_start == "2026-09-14 22:00"
    assert weeks["2026-09-14"].last_close == "2026-09-15 02:00"


def test_publish_keeps_empty_cells_for_missing_tester_day(tmp_path: Path):
    remote = tmp_path / "usage"
    first = UsageTracker(
        tester_name="展玮鸿",
        machine_id="a",
        local_dir=tmp_path / "a",
        remote_dir=remote,
    )
    first.start(_dt("2026-09-15T08:00:00"))
    first.close(_dt("2026-09-15T09:00:00"))
    second = UsageTracker(
        tester_name="黄佳林",
        machine_id="b",
        local_dir=tmp_path / "b",
        remote_dir=remote,
    )
    second.start(_dt("2026-09-16T08:00:00"))
    second.close(_dt("2026-09-16T09:00:00"))

    rows = {row["日期"]: row for row in _read_csv(remote / "汇总_日.csv")}
    assert rows["2026-09-15"]["黄佳林_时长小时"] == ""
    assert rows["2026-09-16"]["展玮鸿_时长小时"] == ""
    publish_usage_csvs(remote)
    assert (remote / "汇总_日.csv").is_file()


def test_main_window_starts_tracker_when_enabled(tmp_path, monkeypatch):
    from src.ui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    remote = tmp_path / "usage"
    remote.mkdir()
    monkeypatch.setattr("src.ui.main_window.usage_tracking_enabled", lambda: True)
    monkeypatch.setattr("src.ui.main_window.default_tester_name", lambda: "展玮鸿")
    monkeypatch.setattr("src.ui.main_window.usage_machine_id", lambda: "test-machine")
    monkeypatch.setattr("src.ui.main_window.local_usage_root", lambda: tmp_path / "local")
    monkeypatch.setattr(
        "src.ui.main_window.resolve_usage_directory", lambda _cfg=None: remote
    )
    win = MainWindow()
    win._prompt_tester_name = lambda **_kwargs: True
    win.show()
    app.processEvents()
    app.processEvents()
    assert win._usage_tracker is not None
    assert (remote / "展玮鸿_日.csv").is_file()
    win._record_usage_report()
    win._record_usage_original_record()
    rows = _read_csv(remote / "展玮鸿_日.csv")
    assert rows[0]["报告数"] == "1"
    assert rows[0]["原始记录数"] == "1"
    win.close()
