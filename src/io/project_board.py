"""Lightweight index of saved project JSON for the hidden personal board.

Does not load ``ProjectState`` (that would decode embedded standard images).
Excel workbook tabs (奥托 / 孔 / …) are out of scope; this reads ``data/``.
"""

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from src.io.network_sources import normalize_config_path
from src.io.project_mirror import default_data_root, list_saved_projects
from src.io.to_numbers import format_to_numbers_display

# Year folder lives under this share as ``{year}年``; month dirs are one level below.
PROJECT_INTRANET_SHARE = "smb://10.10.31.8/材料实验室b/车载电子"

BOARD_COLUMNS: Tuple[str, ...] = (
    "序号",
    "项目号",
    "样品名称",
    "TO号",
    "试验项目",
    "标准",
    "项目状态",
    "开始时间",
    "结束时间",
    "样品数量",
    "备注",
)

_STANDARD_HINT_KEYS = ("standard_id", "standard_chapter", "standard_test_name")
_HIGHLIGHT_BG = "rgba(0, 255, 255, 0.55)"


def project_intranet_year_root(year: int, share: Optional[str] = None) -> str:
    base = (PROJECT_INTRANET_SHARE if share is None else share) or ""
    base = base.strip().rstrip("/\\")
    if not base:
        return ""
    return f"{base}/{int(year)}年"


def resolve_intranet_year_root(year: int, share: Optional[str] = None) -> Optional[Path]:
    raw = project_intranet_year_root(year, share)
    if not raw:
        return None
    return Path(normalize_config_path(raw))


def intranet_year_root_ready(
    year: int,
    *,
    share: Optional[str] = None,
    year_root: Optional[Path] = None,
) -> bool:
    root = year_root if year_root is not None else resolve_intranet_year_root(year, share)
    return root is not None and _is_dir(root)


def request_intranet_share_mount(share: Optional[str] = None) -> None:
    """Ask Finder to mount the SMB share. No-op off macOS."""
    if sys.platform != "darwin":
        return
    raw = (PROJECT_INTRANET_SHARE if share is None else share) or ""
    text = raw.strip()
    if text.startswith("smb://"):
        without_scheme = text[6:]
    elif text.startswith("\\\\"):
        without_scheme = text.lstrip("\\").replace("\\", "/")
    else:
        return
    parts = [p for p in without_scheme.split("/") if p]
    if len(parts) < 2:
        return
    subprocess.run(["open", f"smb://{parts[0]}/{parts[1]}"], check=False)


def find_project_intranet_dir(
    project_id: str,
    year: int,
    *,
    share: Optional[str] = None,
    year_root: Optional[Path] = None,
) -> Optional[Path]:
    """Find the folder under ``{year}年`` whose name contains the A-number.

    Looks at the year folder itself and one level of month subfolders.
    Exact name matches return immediately so a later month is not scanned.
    """
    pid = (project_id or "").strip()
    if not pid:
        return None
    root = year_root if year_root is not None else resolve_intranet_year_root(year, share)
    if root is None or not _is_dir(root):
        return None
    needle = pid.lower()
    prefixed: List[Path] = []
    substring: List[Path] = []
    for entry in _safe_scandir_dirs(root):
        hit = _match_intranet_name(entry, needle)
        if hit == "exact":
            return entry
        if hit == "prefixed":
            prefixed.append(entry)
        elif hit == "substring":
            substring.append(entry)
        for child in _safe_scandir_dirs(entry):
            child_hit = _match_intranet_name(child, needle)
            if child_hit == "exact":
                return child
            if child_hit == "prefixed":
                prefixed.append(child)
            elif child_hit == "substring":
                substring.append(child)
    if prefixed:
        return prefixed[0]
    if substring:
        return substring[0]
    return None


@dataclass(frozen=True)
class IntranetLocateResult:
    status: str
    path: Optional[Path] = None


def locate_project_intranet_folder(
    project_id: str,
    year: int,
    *,
    share: Optional[str] = None,
    year_root: Optional[Path] = None,
) -> IntranetLocateResult:
    """Ready / missing / found, for a background lookup off the UI thread."""
    if not intranet_year_root_ready(year, share=share, year_root=year_root):
        return IntranetLocateResult("not_ready")
    found = find_project_intranet_dir(
        project_id, year, share=share, year_root=year_root
    )
    if found is None:
        return IntranetLocateResult("missing")
    return IntranetLocateResult("found", found)


def open_folder_in_file_manager(
    path: Path | str,
    *,
    platform: Optional[str] = None,
    popen: Optional[Callable[..., object]] = None,
) -> None:
    """Open a folder without blocking on ShellExecute/QUrl.

    Windows uses ``explorer`` via Popen so a slow UNC path cannot freeze Qt.
    """
    target = os.fspath(path)
    plat = sys.platform if platform is None else platform
    launch = popen or subprocess.Popen
    if plat == "win32" or plat.startswith("win"):
        launch(["explorer", target], close_fds=False)
        return
    if plat == "darwin":
        launch(["open", target])
        return
    launch(["xdg-open", target])


def _match_intranet_name(path: Path, needle: str) -> str:
    name = path.name.lower()
    if name == needle:
        return "exact"
    if needle not in name:
        return ""
    if name.startswith(needle):
        return "prefixed"
    return "substring"


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_scandir_dirs(path: Path) -> List[Path]:
    try:
        with os.scandir(path) as entries:
            found: List[Path] = []
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        found.append(Path(entry.path))
                except OSError:
                    continue
            return found
    except OSError:
        return []


def highlight_spans(text: str, query: str) -> List[Tuple[int, int]]:
    needle = (query or "").strip()
    haystack = text or ""
    if not needle or not haystack:
        return []
    lower = haystack.lower()
    n = needle.lower()
    spans: List[Tuple[int, int]] = []
    start = 0
    step = max(len(needle), 1)
    while True:
        idx = lower.find(n, start)
        if idx < 0:
            break
        spans.append((idx, idx + len(needle)))
        start = idx + step
    return spans


def highlight_html(text: str, query: str, bg: str = _HIGHLIGHT_BG) -> str:
    source = text or ""
    spans = highlight_spans(source, query)
    if not spans:
        return html.escape(source)
    parts: List[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(html.escape(source[cursor:start]))
        parts.append(
            f'<span style="background-color:{bg};color:#0A0E14">'
            f"{html.escape(source[start:end])}</span>"
        )
        cursor = end
    parts.append(html.escape(source[cursor:]))
    return "".join(parts)


def parse_iso_date(value) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def format_iso_date(value: Optional[date]) -> str:
    if value is None:
        return ""
    return value.isoformat()


def board_progress_ratio(
    start: Optional[date],
    end: Optional[date],
    today: date,
) -> Optional[float]:
    if start is None or end is None:
        return None
    if end <= start:
        if today < start:
            return 0.0
        return 1.0
    elapsed = (today - start).days
    total = (end - start).days
    return max(0.0, min(1.0, elapsed / total))


@dataclass(frozen=True)
class BoardRow:
    project_id: str
    sample_name: str
    sample_qty: str
    project_sample_qty: str
    applicant: str
    start: Optional[date]
    end: Optional[date]
    tester_name: str
    test_name: str
    standards_text: str
    to_number: str
    notes: str
    json_path: Path
    overdue: bool
    progress: Optional[float]
    leg_index: Optional[int] = None
    node_index: Optional[int] = None

    def search_blob(self) -> str:
        bits = [
            self.project_id,
            self.sample_name,
            self.sample_qty,
            self.project_sample_qty,
            self.applicant,
            format_iso_date(self.start),
            format_iso_date(self.end),
            self.tester_name,
            self.test_name,
            self.standards_text,
            self.to_number,
            self.notes,
        ]
        return " ".join(bits).lower()


@dataclass(frozen=True)
class BoardGroup:
    """One saved project, with its tests folded underneath."""

    project_id: str
    sample_name: str
    sample_qty: str
    applicant: str
    tester_name: str
    start: Optional[date]
    end: Optional[date]
    notes: str
    json_path: Path
    overdue: bool
    progress: Optional[float]
    tests: Tuple[BoardRow, ...]


def filter_board_rows(rows: Sequence[BoardRow], query: str) -> List[BoardRow]:
    needle = (query or "").strip().lower()
    if not needle:
        return list(rows)
    return [row for row in rows if needle in row.search_blob()]


def group_board_rows(
    rows: Sequence[BoardRow],
    *,
    today: Optional[date] = None,
) -> List[BoardGroup]:
    """Fold tests that share a saved project into one parent group."""
    when = today or date.today()
    buckets: dict[Tuple[str, str], List[BoardRow]] = {}
    order: List[Tuple[str, str]] = []
    for row in rows:
        key = (str(row.json_path), row.project_id)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    return [_group_from_tests(buckets[key], when) for key in order]


def _group_from_tests(tests: Sequence[BoardRow], today: date) -> BoardGroup:
    first = tests[0]
    starts = [row.start for row in tests if row.start is not None]
    ends = [row.end for row in tests if row.end is not None]
    start = min(starts) if starts else None
    end = max(ends) if ends else None
    return BoardGroup(
        project_id=first.project_id,
        sample_name=first.sample_name,
        sample_qty=first.project_sample_qty,
        applicant=first.applicant,
        tester_name=_unique_join(row.tester_name for row in tests),
        start=start,
        end=end,
        notes=first.notes,
        json_path=first.json_path,
        overdue=any(row.overdue for row in tests),
        progress=board_progress_ratio(start, end, today),
        tests=tuple(tests),
    )


def _unique_join(values: Iterable[str], sep: str = "、") -> str:
    seen: List[str] = []
    for raw in values:
        text = (raw or "").strip()
        if text and text not in seen:
            seen.append(text)
    return sep.join(seen)


def list_board_rows(
    data_root: Optional[Path] = None,
    *,
    today: Optional[date] = None,
) -> List[BoardRow]:
    root = data_root or default_data_root()
    when = today or date.today()
    rows: List[BoardRow] = []
    for saved in list_saved_projects(root):
        rows.extend(_rows_from_json(saved.json_path, saved.project_id, when))
    return rows


def _rows_from_json(json_path: Path, fallback_id: str, today: date) -> List[BoardRow]:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    fields = data.get("application_fields")
    if not isinstance(fields, dict):
        fields = {}
    project_id = str(data.get("project_id") or "").strip() or fallback_id
    sample_name = str(data.get("sample_name") or fields.get("样品名称") or "").strip()
    project_sample_qty = _sample_qty(fields)
    applicant = str(data.get("applicant_name") or fields.get("申请公司") or "").strip()
    tester_name = str(data.get("tester_name") or "").strip()
    compact_to = str(data.get("to_numbers_display") or "").strip()
    if not compact_to:
        raw_tos = data.get("to_numbers") or []
        if isinstance(raw_tos, list):
            compact_to = format_to_numbers_display(
                [str(item).strip() for item in raw_tos if str(item).strip()]
            )
    named = _iter_named_nodes_indexed(data.get("legs") or [])
    if not named:
        start = parse_iso_date(data.get("test_start_date"))
        end = parse_iso_date(data.get("test_end_date"))
        overdue = end is not None and end < today
        return [
            BoardRow(
                project_id=project_id,
                sample_name=sample_name,
                sample_qty="",
                project_sample_qty=project_sample_qty,
                applicant=applicant,
                start=start,
                end=end,
                tester_name=tester_name,
                test_name="",
                standards_text="",
                to_number=compact_to,
                notes="",
                json_path=json_path,
                overdue=overdue,
                progress=board_progress_ratio(start, end, today),
            )
        ]
    rows: List[BoardRow] = []
    for leg_index, node_index, node in named:
        start = parse_iso_date(node.get("start_date"))
        end = parse_iso_date(node.get("end_date"))
        overdue = end is not None and end < today and not _node_looks_complete(node)
        selected = str(node.get("selected_to") or "").strip()
        rows.append(
            BoardRow(
                project_id=project_id,
                sample_name=sample_name,
                sample_qty=str(node.get("sample_qty") or "").strip(),
                project_sample_qty=project_sample_qty,
                applicant=applicant,
                start=start,
                end=end,
                tester_name=tester_name,
                test_name=str(node.get("test_name") or "").strip(),
                standards_text=_standards_text(node),
                to_number=selected or compact_to,
                notes="",
                json_path=json_path,
                overdue=overdue,
                progress=board_progress_ratio(start, end, today),
                leg_index=leg_index,
                node_index=node_index,
            )
        )
    return rows


def _sample_qty(fields: dict) -> str:
    for key in ("送样数量", "客户送样数量"):
        text = str(fields.get(key) or "").strip()
        if text:
            return text
    return ""


def update_board_sample_qty(json_path: Path, sample_qty: str) -> bool:
    """Patch ``送样数量`` in project JSON without loading ``ProjectState``.

    Also mirrors into the active ``application_columns`` entry when present, so a
    later sample-column sync does not wipe the board edit. Returns False if the
    file cannot be read or written.
    """
    path = Path(json_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    qty = (sample_qty or "").strip()
    fields = data.get("application_fields")
    fields = dict(fields) if isinstance(fields, dict) else {}
    if qty:
        fields["送样数量"] = qty
    else:
        fields.pop("送样数量", None)
        fields.pop("客户送样数量", None)
    data["application_fields"] = fields
    _patch_active_sample_column_qty(data, qty)
    try:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


def update_board_test_sample_qty(
    json_path: Path,
    leg_index: int,
    node_index: int,
    sample_qty: str,
) -> bool:
    """Patch one test node's ``sample_qty`` without loading ``ProjectState``."""
    path = Path(json_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    legs = data.get("legs")
    if not isinstance(legs, list) or leg_index < 0 or leg_index >= len(legs):
        return False
    leg = legs[leg_index]
    if not isinstance(leg, dict):
        return False
    nodes = leg.get("nodes")
    if not isinstance(nodes, list) or node_index < 0 or node_index >= len(nodes):
        return False
    node = nodes[node_index]
    if not isinstance(node, dict):
        return False
    node = dict(node)
    qty = (sample_qty or "").strip()
    if qty:
        node["sample_qty"] = qty
    else:
        node.pop("sample_qty", None)
    nodes[node_index] = node
    leg = dict(leg)
    leg["nodes"] = nodes
    legs[leg_index] = leg
    data["legs"] = legs
    try:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


def _patch_active_sample_column_qty(data: dict, qty: str) -> None:
    columns = data.get("application_columns")
    if not isinstance(columns, list) or not columns:
        return
    try:
        idx = int(data.get("active_sample_column_index", 0) or 0)
    except (TypeError, ValueError):
        idx = 0
    if idx < 0 or idx >= len(columns):
        return
    col = columns[idx]
    if not isinstance(col, dict):
        return
    col = dict(col)
    if qty:
        col["送样数量"] = qty
    else:
        col.pop("送样数量", None)
        col.pop("客户送样数量", None)
    columns[idx] = col
    data["application_columns"] = columns


def _iter_named_nodes_indexed(legs: Iterable) -> List[Tuple[int, int, dict]]:
    out: List[Tuple[int, int, dict]] = []
    if not isinstance(legs, list):
        return out
    for leg_index, leg in enumerate(legs):
        if not isinstance(leg, dict):
            continue
        nodes = leg.get("nodes") or []
        if not isinstance(nodes, list):
            continue
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            if str(node.get("test_name") or "").strip():
                out.append((leg_index, node_index, node))
    return out


def _iter_named_nodes(legs: Iterable) -> List[dict]:
    return [node for _, _, node in _iter_named_nodes_indexed(legs)]


def _standard_ref_label(standard_id, chapter) -> str:
    return " / ".join(
        p for p in (str(standard_id or "").strip(), str(chapter or "").strip()) if p
    )


def _standards_text(node: dict) -> str:
    labels: List[str] = []
    standards = node.get("standards") or []
    if isinstance(standards, list):
        for std in standards:
            if not isinstance(std, dict):
                continue
            label = _standard_ref_label(
                std.get("standard_id"),
                std.get("chapter") or std.get("standard_chapter"),
            )
            if label:
                labels.append(label)
    if labels:
        return "；".join(labels)
    return _standard_ref_label(node.get("standard_id"), node.get("standard_chapter"))


def _node_looks_complete(node: dict) -> bool:
    standards = node.get("standards") or []
    has_standard = isinstance(standards, list) and bool(standards)
    if not has_standard:
        has_standard = any(
            str(node.get(key) or "").strip() for key in _STANDARD_HINT_KEYS
        )
    equipments = node.get("equipments") or []
    has_equipment = bool(str(node.get("equipment_name") or "").strip())
    if not has_equipment and isinstance(equipments, list):
        has_equipment = any(
            isinstance(eq, dict)
            and (
                str(eq.get("name") or "").strip()
                or str(eq.get("code") or "").strip()
            )
            for eq in equipments
        )
    samples = node.get("samples") or []
    has_results = isinstance(samples, list) and any(
        isinstance(sample, dict) and str(sample.get("sample_id") or "").strip()
        for sample in samples
    )
    params_ok = True
    if isinstance(standards, list):
        for std in standards:
            if not isinstance(std, dict):
                continue
            defaults = std.get("key_params_defaults") or []
            if defaults and not std.get("key_params_confirmed"):
                params_ok = False
                break
    return bool(has_standard and has_equipment and has_results and params_ok)
