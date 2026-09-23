"""Silent per-tester usage logs written to the 公盘 usage folder."""

from __future__ import annotations

import csv
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional

from src.io.project_mirror import default_data_root

_SOURCES_DIR = ".sources"
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')
KIND_REPORT = "report"
KIND_ORIGINAL = "original_record"


@dataclass(frozen=True)
class SessionSlice:
    session_id: str
    date: str
    start: str
    end: str
    hours: float


@dataclass(frozen=True)
class CountEvent:
    event_id: str
    date: str
    kind: str


@dataclass
class TesterSource:
    tester_name: str
    machine_id: str
    sessions: list[SessionSlice] = field(default_factory=list)
    events: list[CountEvent] = field(default_factory=list)


@dataclass(frozen=True)
class DayUsage:
    first_start: str
    last_close: str
    duration_hours: float
    report_count: int
    original_record_count: int


@dataclass(frozen=True)
class WeekUsage:
    first_start: str
    last_close: str
    duration_hours: float
    report_count: int
    original_record_count: int


def usage_tracking_enabled() -> bool:
    """Off under pytest so window tests do not touch the real 公盘 folder."""
    return not os.environ.get("PYTEST_CURRENT_TEST")


def local_usage_root(data_root: Optional[Path] = None) -> Path:
    return (data_root or default_data_root()) / "usage_local"


def resolve_usage_directory(config=None) -> Optional[Path]:
    from src.io.network_sources import load_network_sources_config, normalize_config_path

    cfg = config or load_network_sources_config()
    raw = (getattr(getattr(cfg, "usage_stats", None), "directory", None) or "").strip()
    if not raw:
        return None
    path = Path(normalize_config_path(raw))
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        return path if path.is_dir() else None
    except OSError:
        return None


def safe_tester_stem(name: str) -> str:
    text = _BAD_NAME.sub("_", (name or "").strip())
    return (text[:80] or "unknown")


def source_filename(tester_name: str, machine_id: str) -> str:
    return f"{safe_tester_stem(tester_name)}__{machine_id}.json"


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def session_slices(
    session_id: str,
    start: datetime,
    end: datetime,
    *,
    closed: bool,
) -> list[SessionSlice]:
    del closed  # slices are derived from the end timestamp either way
    if end < start:
        end = start
    last_day = end.date()
    ends_at_midnight = end.time() == time.min and end > start
    if ends_at_midnight:
        last_day = (end - timedelta(seconds=1)).date()

    slices: list[SessionSlice] = []
    day = start.date()
    while day <= last_day:
        if day == start.date():
            seg_start = start
        else:
            seg_start = datetime.combine(day, time.min)
        if day < last_day or ends_at_midnight:
            seg_end = datetime.combine(day + timedelta(days=1), time.min)
            end_label = "24:00"
        else:
            seg_end = end
            end_label = _hhmm(end)
        hours = round((seg_end - seg_start).total_seconds() / 3600.0, 2)
        slices.append(
            SessionSlice(
                session_id=session_id,
                date=day.isoformat(),
                start=_hhmm(seg_start) if seg_start.time() != time.min else "00:00",
                end=end_label,
                hours=hours,
            )
        )
        day += timedelta(days=1)
    return slices


def aggregate_days(
    sessions: Iterable[SessionSlice],
    events: Iterable[CountEvent],
) -> dict[str, DayUsage]:
    by_date: dict[str, list[SessionSlice]] = {}
    for item in sessions:
        by_date.setdefault(item.date, []).append(item)
    event_dates = {item.date for item in events}
    days = sorted(set(by_date) | event_dates)
    result: dict[str, DayUsage] = {}
    for day in days:
        slices = by_date.get(day, [])
        day_events = [item for item in events if item.date == day]
        first_start = min((item.start for item in slices), key=_time_key) if slices else ""
        last_close = max((item.end for item in slices), key=_time_key) if slices else ""
        hours = round(sum(item.hours for item in slices), 2)
        result[day] = DayUsage(
            first_start=first_start,
            last_close=last_close,
            duration_hours=hours,
            report_count=sum(1 for item in day_events if item.kind == KIND_REPORT),
            original_record_count=sum(
                1 for item in day_events if item.kind == KIND_ORIGINAL
            ),
        )
    return result


def aggregate_weeks(days: dict[str, DayUsage]) -> dict[str, WeekUsage]:
    buckets: dict[str, list[tuple[str, DayUsage]]] = {}
    for day_text, usage in days.items():
        day = date.fromisoformat(day_text)
        buckets.setdefault(monday_of(day).isoformat(), []).append((day_text, usage))
    result: dict[str, WeekUsage] = {}
    for week, items in buckets.items():
        items = sorted(items, key=lambda pair: pair[0])
        first_day, first = min(
            items,
            key=lambda pair: (pair[0], _time_key(pair[1].first_start or "23:59")),
        )
        last_day, last = max(
            items,
            key=lambda pair: (pair[0], _time_key(pair[1].last_close or "00:00")),
        )
        result[week] = WeekUsage(
            first_start=f"{first_day} {first.first_start}" if first.first_start else "",
            last_close=f"{last_day} {last.last_close}" if last.last_close else "",
            duration_hours=round(sum(item.duration_hours for _day, item in items), 2),
            report_count=sum(item.report_count for _day, item in items),
            original_record_count=sum(item.original_record_count for _day, item in items),
        )
    return dict(sorted(result.items()))


def load_tester_source(
    folder: Path,
    tester_name: str,
    machine_id: str,
) -> Optional[TesterSource]:
    return read_source(Path(folder) / source_filename(tester_name, machine_id))


def read_source(path: Path) -> Optional[TesterSource]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    sessions = [
        SessionSlice(
            session_id=str(item.get("session_id") or ""),
            date=str(item.get("date") or ""),
            start=str(item.get("start") or ""),
            end=str(item.get("end") or ""),
            hours=float(item.get("hours") or 0),
        )
        for item in (data.get("sessions") or [])
        if isinstance(item, dict)
    ]
    events = [
        CountEvent(
            event_id=str(item.get("event_id") or ""),
            date=str(item.get("date") or ""),
            kind=str(item.get("kind") or ""),
        )
        for item in (data.get("events") or [])
        if isinstance(item, dict)
    ]
    return TesterSource(
        tester_name=str(data.get("tester_name") or "").strip(),
        machine_id=str(data.get("machine_id") or "").strip(),
        sessions=sessions,
        events=events,
    )


def write_source(path: Path, source: TesterSource) -> None:
    payload = {
        "tester_name": source.tester_name,
        "machine_id": source.machine_id,
        "sessions": [asdict(item) for item in source.sessions],
        "events": [asdict(item) for item in source.events],
    }
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def iter_sources(folder: Path) -> list[TesterSource]:
    if not folder.is_dir():
        return []
    found: list[TesterSource] = []
    try:
        paths = list(folder.glob("*.json"))
    except OSError:
        return []
    for path in paths:
        source = read_source(path)
        if source is not None and source.tester_name:
            found.append(source)
    return found


def publish_usage_csvs(remote_dir: Path) -> None:
    sources = iter_sources(Path(remote_dir) / _SOURCES_DIR)
    by_name: dict[str, list[TesterSource]] = {}
    for source in sources:
        by_name.setdefault(source.tester_name, []).append(source)
    names = sorted(by_name)
    daily_by_name: dict[str, dict[str, DayUsage]] = {}
    weekly_by_name: dict[str, dict[str, WeekUsage]] = {}
    for name in names:
        sessions: list[SessionSlice] = []
        events: list[CountEvent] = []
        for source in by_name[name]:
            sessions.extend(source.sessions)
            events.extend(source.events)
        days = aggregate_days(sessions, events)
        daily_by_name[name] = days
        weekly_by_name[name] = aggregate_weeks(days)
        _write_person_daily(Path(remote_dir) / f"{safe_tester_stem(name)}_日.csv", days)
        _write_person_weekly(
            Path(remote_dir) / f"{safe_tester_stem(name)}_周.csv",
            weekly_by_name[name],
        )
    _write_summary_daily(Path(remote_dir) / "汇总_日.csv", names, daily_by_name)
    _write_summary_weekly(Path(remote_dir) / "汇总_周.csv", names, weekly_by_name)


_KEEP_REMOTE = object()


@dataclass(frozen=True)
class _UsageFlushJob:
    source: TesterSource
    local_path: Path
    remote_dir: Optional[Path]


def commit_usage_flush(job: _UsageFlushJob) -> None:
    """Write one captured snapshot. Safe to call off the UI thread."""
    try:
        write_source(job.local_path, job.source)
    except OSError:
        pass
    remote = job.remote_dir
    if remote is None:
        return
    try:
        remote.mkdir(parents=True, exist_ok=True)
        (remote / _SOURCES_DIR).mkdir(parents=True, exist_ok=True)
        if not remote.is_dir():
            return
        write_source(
            remote / _SOURCES_DIR / source_filename(job.source.tester_name, job.source.machine_id),
            job.source,
        )
        publish_usage_csvs(remote)
    except OSError:
        return


class UsageTracker:
    def __init__(
        self,
        *,
        tester_name: str,
        machine_id: str,
        local_dir: Path,
        remote_dir: Optional[Path],
    ) -> None:
        self.tester_name = (tester_name or "").strip()
        self.machine_id = machine_id
        self.local_dir = Path(local_dir)
        self.remote_dir = Path(remote_dir) if remote_dir is not None else None
        self.session_id: Optional[str] = None
        self.session_start: Optional[datetime] = None
        self._sessions: list[SessionSlice] = []
        self._events: list[CountEvent] = []
        self._loaded = False
        self._lock = threading.RLock()

    def open_session(self, now: datetime) -> None:
        """Remember that a session is open. Disk and 公盘 writes stay in flush."""
        with self._lock:
            if not self.tester_name or self.session_id is not None:
                return
            self.session_id = uuid.uuid4().hex
            self.session_start = now

    def start(self, now: datetime) -> None:
        with self._lock:
            if not self.tester_name or self.session_id is not None:
                return
            self._ensure_loaded()
            self.session_id = uuid.uuid4().hex
            self.session_start = now
        self.flush(now, closed=False)

    def tick(self, now: datetime) -> None:
        self.flush(now, closed=False)

    def close(self, now: datetime) -> None:
        self.flush(now, closed=True)

    def rename_tester(self, new_name: str, now: datetime) -> None:
        name = (new_name or "").strip()
        if not name or name == self.tester_name:
            return
        self.close(now)
        with self._lock:
            self.tester_name = name
            self._sessions = []
            self._events = []
            self._loaded = False
        self.start(now)

    def record_report(self, now: datetime) -> None:
        self._record_event(KIND_REPORT, now)

    def record_original_record(self, now: datetime) -> None:
        self._record_event(KIND_ORIGINAL, now)

    def flush(self, now: datetime, *, closed: bool = False) -> None:
        job = self.capture_flush(now, closed=closed)
        if job is not None:
            commit_usage_flush(job)

    def capture_flush(
        self,
        now: datetime,
        *,
        closed: bool = False,
        remote_dir: object = _KEEP_REMOTE,
    ) -> Optional[_UsageFlushJob]:
        """Update memory and return the files to write. Does not touch disk."""
        with self._lock:
            if remote_dir is not _KEEP_REMOTE:
                self.remote_dir = Path(remote_dir) if remote_dir is not None else None
            if not self.tester_name:
                return None
            actually_closed = closed and self.session_id is not None
            self._ensure_loaded()
            self._replace_open_slices(now, closed=actually_closed)
            source = TesterSource(
                tester_name=self.tester_name,
                machine_id=self.machine_id,
                sessions=list(self._sessions),
                events=list(self._events),
            )
            local_path = self.local_dir / source_filename(self.tester_name, self.machine_id)
            remote = self.remote_dir
            if actually_closed:
                self.session_id = None
                self.session_start = None
            return _UsageFlushJob(source=source, local_path=local_path, remote_dir=remote)

    def _record_event(self, kind: str, now: datetime) -> None:
        with self._lock:
            self._ensure_loaded()
            self._events.append(
                CountEvent(event_id=uuid.uuid4().hex, date=now.date().isoformat(), kind=kind)
            )
            need_start = self.session_id is None
        if need_start:
            self.start(now)
            return
        self.flush(now, closed=False)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        source = load_tester_source(self.local_dir, self.tester_name, self.machine_id)
        if source is None:
            remote = self._ensure_remote()
            if remote is not None:
                source = load_tester_source(
                    remote / _SOURCES_DIR, self.tester_name, self.machine_id
                )
        if source is not None:
            self._sessions = list(source.sessions)
            self._events = list(source.events)
        self._loaded = True

    def _replace_open_slices(self, now: datetime, *, closed: bool) -> None:
        if self.session_id is None or self.session_start is None:
            return
        fresh = session_slices(
            self.session_id, self.session_start, now, closed=closed
        )
        self._sessions = [
            item for item in self._sessions if item.session_id != self.session_id
        ]
        self._sessions.extend(fresh)

    def _ensure_remote(self) -> Optional[Path]:
        if self.remote_dir is None:
            return None
        try:
            self.remote_dir.mkdir(parents=True, exist_ok=True)
            (self.remote_dir / _SOURCES_DIR).mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        try:
            return self.remote_dir if self.remote_dir.is_dir() else None
        except OSError:
            return None


def _hhmm(value: datetime) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _time_key(hhmm: str) -> tuple[int, int]:
    if hhmm == "24:00":
        return (24, 0)
    try:
        hour, minute = hhmm.split(":")
        return (int(hour), int(minute))
    except (TypeError, ValueError):
        return (0, 0)


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    from io import StringIO

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    _atomic_write_text(path, buf.getvalue(), encoding="utf-8-sig")


def _person_headers(*, week: bool) -> list[str]:
    first = "周起始" if week else "日期"
    return [first, "首次启动", "末次关闭", "时长小时", "报告数", "原始记录数"]


def _write_person_daily(path: Path, days: dict[str, DayUsage]) -> None:
    rows = [
        [
            day,
            usage.first_start,
            usage.last_close,
            f"{usage.duration_hours:.2f}",
            str(usage.report_count),
            str(usage.original_record_count),
        ]
        for day, usage in sorted(days.items())
    ]
    _write_csv(path, _person_headers(week=False), rows)


def _write_person_weekly(path: Path, weeks: dict[str, WeekUsage]) -> None:
    rows = [
        [
            week,
            usage.first_start,
            usage.last_close,
            f"{usage.duration_hours:.2f}",
            str(usage.report_count),
            str(usage.original_record_count),
        ]
        for week, usage in sorted(weeks.items())
    ]
    _write_csv(path, _person_headers(week=True), rows)


def _summary_headers(names: list[str], *, week: bool) -> list[str]:
    first = "周起始" if week else "日期"
    cols = [first]
    for name in names:
        cols.extend(
            [
                f"{name}_首次启动",
                f"{name}_末次关闭",
                f"{name}_时长小时",
                f"{name}_报告数",
                f"{name}_原始记录数",
            ]
        )
    return cols


def _summary_cells(usage: Optional[DayUsage | WeekUsage]) -> list[str]:
    if usage is None:
        return ["", "", "", "", ""]
    return [
        usage.first_start,
        usage.last_close,
        f"{usage.duration_hours:.2f}",
        str(usage.report_count),
        str(usage.original_record_count),
    ]


def _write_summary_daily(
    path: Path,
    names: list[str],
    daily_by_name: dict[str, dict[str, DayUsage]],
) -> None:
    dates = sorted({day for days in daily_by_name.values() for day in days})
    rows = []
    for day in dates:
        row = [day]
        for name in names:
            row.extend(_summary_cells(daily_by_name.get(name, {}).get(day)))
        rows.append(row)
    _write_csv(path, _summary_headers(names, week=False), rows)


def _write_summary_weekly(
    path: Path,
    names: list[str],
    weekly_by_name: dict[str, dict[str, WeekUsage]],
) -> None:
    weeks = sorted({week for items in weekly_by_name.values() for week in items})
    rows = []
    for week in weeks:
        row = [week]
        for name in names:
            row.extend(_summary_cells(weekly_by_name.get(name, {}).get(week)))
        rows.append(row)
    _write_csv(path, _summary_headers(names, week=True), rows)
