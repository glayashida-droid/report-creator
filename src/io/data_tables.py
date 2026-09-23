"""Manage data-table xlsx attachments under 3.测试组/{Leg名}-{试验名}/数据表附件/."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries

from application_parser.sample_id_labels import is_sample_id_column_key

from src.language_copy import table_header_label
from src.io.network_sources import data_table_templates_directory
from src.io.test_photos import (
    PhotoError,
    TEST_GROUP_DIR,
    require_leg_name as require_photo_leg_name,
    require_usable_test_name as require_photo_test_name,
    test_dir,
)
from src.models.project_state import DataTableRef, TestNode

ATTACHMENT_DIR = "数据表附件"
EMPTY_LIMIT_DISPLAY = "/"
_CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')
_BOUND_LABEL_SEP_RE = re.compile(r"[\s/／|]+")

# macOS .app bundle names / Windows executable stems, preferred order
_EXCEL_APP_NAMES = ("Microsoft Excel",)
_WPS_APP_NAMES = ("wpsoffice", "WPS Office", "kingsoft")


def default_templates_dir() -> Path:
    from src.io.source_mirror import prefer_local_tree

    return prefer_local_tree("data_tables", data_table_templates_directory)


class DataTableError(Exception):
    pass


def rewrite_test_dir_in_relative_path(
    relative_path: str, old_dir_key: str, new_dir_key: str
) -> str:
    """Rewrite 3.测试组/{old}/… → 3.测试组/{new}/… in a stored attachment path."""
    old = (old_dir_key or "").strip()
    new = (new_dir_key or "").strip()
    rel = (relative_path or "").replace("\\", "/")
    if not old or not new or old == new or not rel:
        return relative_path or ""
    old_prefix = f"{TEST_GROUP_DIR}/{old}/"
    if rel.startswith(old_prefix):
        return f"{TEST_GROUP_DIR}/{new}/" + rel[len(old_prefix) :]
    return rel


def retarget_node_data_tables(node: TestNode, old_dir_key: str, new_dir_key: str) -> None:
    """Update data_tables relative_path prefixes after a trial folder rename."""
    refs = list(getattr(node, "data_tables", None) or [])
    if not refs:
        return
    node.data_tables = [
        DataTableRef(
            title=ref.title,
            relative_path=rewrite_test_dir_in_relative_path(
                ref.relative_path, old_dir_key, new_dir_key
            ),
        )
        for ref in refs
    ]


@dataclass
class PreviewSnapshot:
    """Readonly first-sheet bbox: values as strings, empty cells kept, merges as A1:B2."""

    sheet_name: str
    values: List[List[str]] = field(default_factory=list)
    merges: List[str] = field(default_factory=list)
    # 1-based origin of values[0][0] in the sheet (for mapping merge refs onto the grid)
    origin_row: int = 1
    origin_col: int = 1


def attachment_dir(project_root: Path, leg_name: str, test_name: str) -> Path:
    return test_dir(project_root, leg_name, test_name) / ATTACHMENT_DIR


def list_attachment_refs(
    project_root: Path, leg_name: str, test_name: str
) -> List[DataTableRef]:
    """Scan 数据表附件 for .xlsx files; title = stem; sorted by filename."""
    try:
        leg = _require_leg_name(leg_name)
        test = _require_usable_test_name(test_name)
    except DataTableError:
        return []
    folder = attachment_dir(project_root, leg, test)
    if not folder.is_dir():
        return []
    root = Path(project_root)
    refs: List[DataTableRef] = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file():
            continue
        if path.suffix.lower() != ".xlsx":
            continue
        if path.name.startswith("~$"):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        refs.append(DataTableRef(title=path.stem, relative_path=rel))
    return refs


def _require_leg_name(leg_name: str) -> str:
    try:
        return require_photo_leg_name(leg_name)
    except PhotoError as exc:
        raise DataTableError(str(exc)) from exc


def _require_usable_test_name(test_name: str) -> str:
    try:
        return require_photo_test_name(test_name)
    except PhotoError as exc:
        raise DataTableError(str(exc)) from exc


def sanitize_filename_stem(title: str) -> str:
    text = _BAD_NAME.sub("_", (title or "").strip())
    text = text.strip(" .")
    return text or "未命名数据表"


def unique_xlsx_path(folder: Path, stem: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / f"{stem}.xlsx"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = folder / f"{stem}-{n}.xlsx"
        if not candidate.exists():
            return candidate
        n += 1


def create_blank_workbook(
    project_root: Path, leg_name: str, test_name: str, title: str
) -> DataTableRef:
    """Create an empty xlsx in the attachment folder; return an index ref."""
    leg = _require_leg_name(leg_name)
    test = _require_usable_test_name(test_name)
    name = (title or "").strip()
    if not name:
        raise DataTableError("请输入数据表标题")
    folder = attachment_dir(project_root, leg, test)
    stem = sanitize_filename_stem(name)
    dest = unique_xlsx_path(folder, stem)
    wb = Workbook()
    wb.save(dest)
    wb.close()
    rel = dest.relative_to(Path(project_root)).as_posix()
    return DataTableRef(title=name, relative_path=rel)


def upload_existing_xlsx(
    project_root: Path, leg_name: str, test_name: str, source: Path
) -> DataTableRef:
    """Copy an existing .xlsx into the attachment folder; title is the filename stem."""
    leg = _require_leg_name(leg_name)
    test = _require_usable_test_name(test_name)
    src = Path(source)
    if not src.is_file():
        raise DataTableError("找不到所选 Excel 文件")
    if src.suffix.lower() != ".xlsx":
        raise DataTableError("仅支持 .xlsx 文件")
    folder = attachment_dir(project_root, leg, test)
    stem = sanitize_filename_stem(src.stem)
    dest = unique_xlsx_path(folder, stem)
    shutil.copy2(src, dest)
    title = stem
    rel = dest.relative_to(Path(project_root)).as_posix()
    return DataTableRef(title=title, relative_path=rel)


def list_data_table_templates(templates_dir: Path | None = None) -> List[Path]:
    """List .xlsx files in the app-level templates folder (sorted by name)."""
    folder = Path(templates_dir) if templates_dir is not None else default_templates_dir()
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".xlsx"),
        key=lambda p: p.name.lower(),
    )


def copy_from_template(
    project_root: Path, leg_name: str, test_name: str, template_path: Path
) -> DataTableRef:
    """Copy a template .xlsx into the attachment folder (same semantics as upload)."""
    return upload_existing_xlsx(project_root, leg_name, test_name, template_path)


def _col1_has_content(ws) -> bool:
    for row in ws.iter_rows(min_col=1, max_col=1):
        for cell in row:
            if _is_nonempty(cell.value):
                return True
    return False


def _sample_id_col_merge_bottom(ws) -> dict[int, int]:
    """Row index in column A -> bottom row of its vertical merge (or itself)."""
    out: dict[int, int] = {}
    for rng in ws.merged_cells.ranges:
        if rng.min_col > 1 or rng.max_col < 1:
            continue
        for r in range(rng.min_row, rng.max_row + 1):
            out[r] = max(out.get(r, r), rng.max_row)
    return out


def _classify_bound_label(text: str) -> str | None:
    """Return 'upper' / 'lower' for 上限·下限 / upper·lower (incl. bilingual)."""
    raw = (text or "").strip()
    if not raw:
        return None
    compact = _BOUND_LABEL_SEP_RE.sub("", raw)
    key = compact.casefold()
    if compact in {"上限", "数据上限"} or key == "upper" or key in {
        "上限upper",
        "upper上限",
        "数据上限upper",
        "upper数据上限",
    }:
        return "upper"
    if compact in {"下限", "数据下限"} or key == "lower" or key in {
        "下限lower",
        "lower下限",
        "数据下限lower",
        "lower数据下限",
    }:
        return "lower"
    return None


@dataclass(frozen=True)
class BoundRowIndices:
    """0-based preview rows, or 1-based sheet rows, depending on caller."""

    upper: int | None = None
    lower: int | None = None
    label_col: int = 0

    def indices(self) -> tuple[int, ...]:
        return tuple(r for r in (self.upper, self.lower) if r is not None)


def _scan_bound_rows_in_column(ws, col: int, min_r: int, max_r: int) -> BoundRowIndices:
    upper = lower = None
    for r in range(min_r, max_r + 1):
        kind = _classify_bound_label(str(ws.cell(row=r, column=col).value or ""))
        if kind == "upper" and upper is None:
            upper = r
        elif kind == "lower" and lower is None:
            lower = r
    return BoundRowIndices(upper=upper, lower=lower, label_col=col)


def _bound_row_sheet_indices(ws) -> BoundRowIndices:
    """1-based sheet rows/column for 上限/下限 labels (col A, else col B)."""
    bbox = _used_bbox(ws)
    if bbox is None:
        return BoundRowIndices()
    min_r, _min_c, max_r, _max_c = bbox
    for col in (1, 2):
        found = _scan_bound_rows_in_column(ws, col, min_r, max_r)
        if found.indices():
            return found
    return BoundRowIndices()


def _sample_id_start_row(ws) -> int:
    """First row for sample ids: below bound rows if present, else below content/header."""
    bound_rows = _bound_row_sheet_indices(ws).indices()
    if bound_rows:
        return max(bound_rows) + 1
    bbox = _used_bbox(ws)
    if bbox is None:
        return 2
    default_start = bbox[2] + 1
    merge_bottom = _sample_id_col_merge_bottom(ws)
    header_end = max(1, default_start - 1)
    for r in range(1, header_end + 1):
        val = ws.cell(row=r, column=1).value
        if is_sample_id_column_key(str(val or "").strip()):
            return max(default_start, merge_bottom.get(r, r) + 1)
    return default_start


def _sample_id_column_header_text() -> str:
    return table_header_label("样品编号", "Sample No.", "中英文")


def _col1_has_sample_id_header(ws, header_end_row: int) -> bool:
    for r in range(1, header_end_row + 1):
        if is_sample_id_column_key(str(ws.cell(row=r, column=1).value or "").strip()):
            return True
    return False


def _write_sample_id_column_header(ws, header_end_row: int) -> None:
    """Write bilingual 样品编号 / Sample No. into column A for the header band."""
    if header_end_row < 1 or _col1_has_sample_id_header(ws, header_end_row):
        return
    ws.cell(row=1, column=1, value=_sample_id_column_header_text())
    if header_end_row > 1:
        ws.merge_cells(start_row=1, start_column=1, end_row=header_end_row, end_column=1)


def _should_insert_sample_id_column(ws, start_row: int) -> bool:
    """Left-insert only when col 1 holds non-sample-id content."""
    header_end_row = max(1, start_row - 1)
    if _col1_has_sample_id_header(ws, header_end_row):
        return False
    bound = _bound_row_sheet_indices(ws)
    if bound.indices() and min(bound.indices()) < start_row:
        # Bound labels already occupy col A or B — do not insert a third left column.
        return False
    return _col1_has_content(ws)


def _unmerge_overlapping(ws, min_r: int, min_c: int, max_r: int, max_c: int) -> None:
    overlapping = [
        str(rng)
        for rng in ws.merged_cells.ranges
        if not (
            rng.max_row < min_r
            or rng.min_row > max_r
            or rng.max_col < min_c
            or rng.min_col > max_c
        )
    ]
    for ref in overlapping:
        ws.unmerge_cells(ref)


def _ensure_bound_label_column(ws, bound: BoundRowIndices) -> BoundRowIndices:
    """Keep 上限/下限 in column B so sample ids can span A:B."""
    if not bound.indices() or bound.label_col == 2:
        return bound
    ws.insert_cols(2)
    for r in bound.indices():
        ws.cell(row=r, column=2).value = ws.cell(row=r, column=1).value
        ws.cell(row=r, column=1).value = None
    return BoundRowIndices(upper=bound.upper, lower=bound.lower, label_col=2)


def _apply_sample_header_through_bounds(ws, last_bound_row: int) -> None:
    """Merge 样品编号 in column A through the 上限/下限 rows, centered."""
    _unmerge_overlapping(ws, 1, 1, last_bound_row, 1)
    ws.cell(row=1, column=1).value = _sample_id_column_header_text()
    ws.cell(row=1, column=1).alignment = _CENTER_ALIGN
    if last_bound_row > 1:
        ws.merge_cells(
            start_row=1, start_column=1, end_row=last_bound_row, end_column=1
        )


def _write_sample_ids_spanning_label_col(
    ws, start_row: int, sample_ids: Sequence[str]
) -> None:
    """Write ids merged across A:B and centered (图2)."""
    for i, sid in enumerate(sample_ids):
        r = start_row + i
        _unmerge_overlapping(ws, r, 1, r, 2)
        ws.cell(row=r, column=1).value = sid
        ws.cell(row=r, column=2).value = None
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.cell(row=r, column=1).alignment = _CENTER_ALIGN


def _fill_empty_bound_cells(ws, bound: BoundRowIndices) -> None:
    """Write '/' into empty 上限/下限 data cells so the xlsx matches preview."""
    bbox = _used_bbox(ws)
    if bbox is None or not bound.indices():
        return
    _min_r, min_c, _max_r, max_c = bbox
    skip = {1, bound.label_col}
    for r in bound.indices():
        for c in range(min_c, max_c + 1):
            if c in skip:
                continue
            cell = ws.cell(row=r, column=c)
            if isinstance(cell, MergedCell):
                continue
            if not _is_nonempty(cell.value):
                cell.value = EMPTY_LIMIT_DISPLAY


def _merge_sample_id_rows_from(ws, start_row: int) -> None:
    """Merge existing sample-id rows across A:B without changing id values."""
    bbox = _used_bbox(ws)
    if bbox is None:
        return
    max_r = bbox[2]
    for r in range(start_row, max_r + 1):
        cell_a = ws.cell(row=r, column=1)
        if isinstance(cell_a, MergedCell) or not _is_nonempty(cell_a.value):
            continue
        _unmerge_overlapping(ws, r, 1, r, 2)
        cell_b = ws.cell(row=r, column=2)
        if not isinstance(cell_b, MergedCell):
            cell_b.value = None
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.cell(row=r, column=1).alignment = _CENTER_ALIGN


def _apply_bound_display_layout(ws) -> BoundRowIndices:
    """Move bound labels to B, merge 样品编号 through bounds, fill '/'."""
    bound = _bound_row_sheet_indices(ws)
    if not bound.indices():
        return bound
    bound = _ensure_bound_label_column(ws, bound)
    last_bound = max(bound.indices())
    _apply_sample_header_through_bounds(ws, last_bound)
    _fill_empty_bound_cells(ws, bound)
    return bound


def sync_display_layout(path: Path) -> None:
    """Write preview layout into the first sheet without changing sample ids.

    Empty 上限/下限 data cells become '/'; 样品编号 merges through bound rows;
    existing sample-id rows span A:B. No-op when the sheet has no bound rows.
    """
    xlsx = Path(path)
    if not xlsx.is_file():
        raise DataTableError("数据表文件不存在")
    wb = load_workbook(xlsx)
    try:
        ws = wb.worksheets[0]
        bound = _apply_bound_display_layout(ws)
        if bound.indices():
            _merge_sample_id_rows_from(ws, max(bound.indices()) + 1)
            try:
                wb.save(xlsx)
            except OSError as exc:
                raise DataTableError(f"无法写入数据表：{exc}") from exc
    finally:
        wb.close()


def import_sample_ids(path: Path, sample_ids: Sequence[str]) -> None:
    """Write sample ids into the first sheet below existing content; insert col 1 if needed."""
    xlsx = Path(path)
    if not xlsx.is_file():
        raise DataTableError("数据表文件不存在")
    ids = [str(s).strip() for s in sample_ids if str(s).strip()]
    wb = load_workbook(xlsx)
    try:
        ws = wb.worksheets[0]
        start_row = _sample_id_start_row(ws)
        if _should_insert_sample_id_column(ws, start_row):
            ws.insert_cols(1)
            start_row = _sample_id_start_row(ws)
        bound = _bound_row_sheet_indices(ws)
        if bound.indices():
            bound = _ensure_bound_label_column(ws, bound)
            last_bound = max(bound.indices())
            _apply_sample_header_through_bounds(ws, last_bound)
            _write_sample_ids_spanning_label_col(ws, last_bound + 1, ids)
            _fill_empty_bound_cells(ws, bound)
        else:
            header_end_row = max(1, start_row - 1)
            _write_sample_id_column_header(ws, header_end_row)
            for i, sid in enumerate(ids):
                ws.cell(row=start_row + i, column=1, value=sid)
        wb.save(xlsx)
    finally:
        wb.close()


def _default_app_exists(app_name: str) -> bool:
    """True if a macOS .app or a PATH executable named app_name is present."""
    if sys.platform == "darwin":
        candidates = [
            Path("/Applications") / f"{app_name}.app",
            Path.home() / "Applications" / f"{app_name}.app",
        ]
        if any(c.is_dir() for c in candidates):
            return True
    return shutil.which(app_name) is not None


def resolve_open_argv(
    path: Path,
    *,
    platform: Optional[str] = None,
    app_exists: Optional[Callable[[str], bool]] = None,
) -> List[str]:
    """Build argv to open an xlsx: Excel → WPS → system default. Does not launch."""
    target = str(Path(path))
    plat = platform if platform is not None else sys.platform
    exists = app_exists or _default_app_exists

    if plat == "darwin":
        for name in _EXCEL_APP_NAMES:
            if exists(name):
                return ["open", "-a", name, target]
        for name in _WPS_APP_NAMES:
            if exists(name):
                return ["open", "-a", name, target]
        return ["open", target]

    if plat.startswith("win"):
        for name in ("EXCEL.EXE", "excel"):
            exe = shutil.which(name) if app_exists is None else (name if exists(name) else None)
            if exe:
                return [exe, target]
        for name in ("wps", "wpsoffice"):
            exe = shutil.which(name) if app_exists is None else (name if exists(name) else None)
            if exe:
                return [exe, target]
        return ["cmd", "/c", "start", "", target]

    # Linux / other: PATH then xdg-open
    for name in ("excel", "soffice", "wps", "wpsoffice"):
        if exists(name):
            exe = shutil.which(name) or name
            return [exe, target]
    return ["xdg-open", target]


def open_attachment(
    path: Path,
    *,
    runner: Optional[Callable[..., Any]] = None,
    resolve_argv: Optional[Callable[[Path], List[str]]] = None,
) -> None:
    """Open the attachment in an external spreadsheet app. Raises DataTableError on failure."""
    xlsx = Path(path)
    if not xlsx.is_file():
        raise DataTableError("数据表文件不存在")
    argv = (resolve_argv or resolve_open_argv)(xlsx)
    run = runner or subprocess.run
    try:
        result = run(argv, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise DataTableError(f"无法打开数据表：{exc}") from exc
    code = getattr(result, "returncode", 0)
    if code:
        err = (getattr(result, "stderr", None) or getattr(result, "stdout", None) or "").strip()
        detail = f"：{err}" if err else ""
        raise DataTableError(f"无法打开数据表{detail}")


def _cell_display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    if isinstance(value, str):
        return value
    text = str(value).strip()
    if text in {"", "nan", "NaT", "None"}:
        return ""
    return str(value)


def _is_nonempty(value: Any) -> bool:
    return _cell_display(value) != ""


def _used_bbox(ws) -> Tuple[int, int, int, int] | None:
    """Return 1-based (min_row, min_col, max_row, max_col) for nonempty cells, or None."""
    min_r = min_c = max_r = max_c = None
    for row in ws.iter_rows():
        for cell in row:
            if not _is_nonempty(cell.value):
                continue
            r, c = cell.row, cell.column
            min_r = r if min_r is None else min(min_r, r)
            max_r = r if max_r is None else max(max_r, r)
            min_c = c if min_c is None else min(min_c, c)
            max_c = c if max_c is None else max(max_c, c)
    if min_r is None:
        return None
    return min_r, min_c, max_r, max_c


def _merges_in_bbox(
    merges: Sequence, min_r: int, min_c: int, max_r: int, max_c: int
) -> List[str]:
    out: List[str] = []
    for rng in merges:
        # CellRange has min_row/min_col/max_row/max_col
        if rng.max_row < min_r or rng.min_row > max_r:
            continue
        if rng.max_col < min_c or rng.min_col > max_c:
            continue
        out.append(str(rng))
    return out


def _header_count_from_merges(snap: PreviewSnapshot) -> int:
    """Rows touched by a merge starting at/including the first sheet row."""
    if not snap.values:
        return 0
    origin_r = snap.origin_row or 1
    max_header = 0
    touched = False
    for merge in snap.merges or []:
        try:
            min_c, min_r, max_c, max_r = range_boundaries(merge)
        except Exception:
            continue
        r0 = min_r - origin_r
        r1 = max_r - origin_r
        if r0 <= 0 <= r1 or r0 == 0:
            touched = True
            max_header = max(max_header, r1)
    if touched:
        return max_header + 1
    return 0


def _merge_bottom_by_cell(snap: PreviewSnapshot) -> dict[tuple[int, int], int]:
    """Grid (r,c) -> bottom row index of its merge (or r if unmerged)."""
    origin_r = snap.origin_row or 1
    origin_c = snap.origin_col or 1
    out: dict[tuple[int, int], int] = {}
    for merge in snap.merges or []:
        try:
            min_c, min_r, max_c, max_r = range_boundaries(merge)
        except Exception:
            continue
        r0 = min_r - origin_r
        r1 = max_r - origin_r
        c0 = min_c - origin_c
        c1 = max_c - origin_c
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                out[(r, c)] = max(out.get((r, c), r), r1)
    return out


def _header_count_from_sample_id(snap: PreviewSnapshot) -> int | None:
    """First data row is below 样品编号 label band, or first non-label value in column A."""
    values = snap.values or []
    if not values:
        return None
    merge_bottom = _merge_bottom_by_cell(snap)

    label_data_start: int | None = None
    for r, row in enumerate(values):
        for c, val in enumerate(row):
            if is_sample_id_column_key((val or "").strip()):
                bottom = merge_bottom.get((r, c), r)
                start = bottom + 1
                if label_data_start is None or start > label_data_start:
                    label_data_start = start

    if label_data_start is not None:
        return label_data_start

    for r, row in enumerate(values):
        val = (row[0] if row else "").strip()
        if not val or is_sample_id_column_key(val):
            continue
        return r
    return None


def infer_header_row_count(snap: PreviewSnapshot) -> int:
    """How many top rows repeat as table headers on page breaks in Word export."""
    if not snap.values:
        return 0
    merge_count = _header_count_from_merges(snap)
    sample_count = _header_count_from_sample_id(snap)
    if sample_count is not None:
        return max(merge_count, sample_count, 1)
    return max(merge_count, 1)


# Display-string number: optional sign, digits, optional fractional part (no sci notation).
_NUMERIC_DISPLAY_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)$")


def decimal_places(text: str) -> int | None:
    """Decimal digits after '.' in a display string, or None if not a plain number."""
    s = (text or "").strip()
    if not s or not _NUMERIC_DISPLAY_RE.match(s):
        return None
    if "." in s:
        return len(s.split(".", 1)[1])
    return 0


def parse_numeric_display(text: str) -> float | None:
    """Parse a plain numeric display string; None if not parseable as a number."""
    s = (text or "").strip()
    if not s or not _NUMERIC_DISPLAY_RE.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


@dataclass(frozen=True)
class LimitRule:
    """Numeric bound for one column (or whole table). Missing side = unbounded."""

    lo: float | None = None
    hi: float | None = None
    lo_exclusive: bool = False
    hi_exclusive: bool = False


def find_bound_row_indices(
    snap: PreviewSnapshot, *, sample_col: int = 0
) -> BoundRowIndices:
    """0-based grid rows for 上限/下限; labels may sit in sample_col or the next column."""
    values = snap.values or []
    ncols = max((len(r) for r in values), default=0)
    search_cols = [sample_col]
    if sample_col + 1 < ncols:
        search_cols.append(sample_col + 1)
    for c in search_cols:
        upper = lower = None
        for r, row in enumerate(values):
            text = row[c] if c < len(row) else ""
            kind = _classify_bound_label(text)
            if kind == "upper" and upper is None:
                upper = r
            elif kind == "lower" and lower is None:
                lower = r
        if upper is not None or lower is not None:
            return BoundRowIndices(upper=upper, lower=lower, label_col=c)
    return BoundRowIndices(label_col=sample_col)


def has_limit_row(snap: PreviewSnapshot, *, sample_col: int = 0) -> bool:
    return bool(find_bound_row_indices(snap, sample_col=sample_col).indices())


def _skip_limit_cols(bounds: BoundRowIndices, sample_col: int) -> set[int]:
    skip = {sample_col}
    if bounds.label_col != sample_col:
        skip.add(bounds.label_col)
    return skip


def _first_data_col(bounds: BoundRowIndices, sample_col: int) -> int:
    skip = _skip_limit_cols(bounds, sample_col)
    return max(skip) + 1


def _pad_row(row: list[str], ncols: int) -> list[str]:
    while len(row) < ncols:
        row.append("")
    return row


def _cell_text(values: List[List[str]], r: int | None, c: int) -> str:
    if r is None or r < 0 or r >= len(values):
        return ""
    row = values[r]
    return row[c] if c < len(row) else ""


def _occupied_column_bounds(
    snap: PreviewSnapshot, *, sample_col: int = 0
) -> tuple[BoundRowIndices, dict[int, tuple[float | None, float | None]], int]:
    """Per occupied data column: (lower, upper). Occupied = at least one numeric side."""
    bounds = find_bound_row_indices(snap, sample_col=sample_col)
    values = snap.values or []
    ncols = max((len(r) for r in values), default=0)
    skip_cols = _skip_limit_cols(bounds, sample_col)
    per_col: dict[int, tuple[float | None, float | None]] = {}
    for c in range(ncols):
        if c in skip_cols:
            continue
        lo = parse_numeric_display(_cell_text(values, bounds.lower, c))
        hi = parse_numeric_display(_cell_text(values, bounds.upper, c))
        if lo is not None or hi is not None:
            per_col[c] = (lo, hi)
    return bounds, per_col, ncols


def _rule_from_sides(
    lo: float | None, hi: float | None, *, inclusive: bool
) -> LimitRule:
    exclusive = not inclusive
    return LimitRule(
        lo=lo,
        hi=hi,
        lo_exclusive=exclusive if lo is not None else False,
        hi_exclusive=exclusive if hi is not None else False,
    )


def value_violates_limit(val: float, rule: LimitRule) -> bool:
    if rule.lo is not None:
        if rule.lo_exclusive:
            if not (val > rule.lo):
                return True
        elif val < rule.lo:
            return True
    if rule.hi is not None:
        if rule.hi_exclusive:
            if not (val < rule.hi):
                return True
        elif val > rule.hi:
            return True
    return False


def _column_limit_rules(
    snap: PreviewSnapshot, *, sample_col: int = 0, inclusive: bool = True
) -> dict[int, LimitRule] | None:
    """Map data-column index → rule. None if no bound rows; {} if rows but no numbers."""
    bounds, per_col, ncols = _occupied_column_bounds(snap, sample_col=sample_col)
    if not bounds.indices():
        return None
    if not per_col:
        return {}
    if len(per_col) == 1:
        lo, hi = next(iter(per_col.values()))
        rule = _rule_from_sides(lo, hi, inclusive=inclusive)
        skip_cols = _skip_limit_cols(bounds, sample_col)
        return {c: rule for c in range(ncols) if c not in skip_cols}
    return {
        c: _rule_from_sides(lo, hi, inclusive=inclusive)
        for c, (lo, hi) in per_col.items()
    }


def find_out_of_range_by_limits(
    snap: PreviewSnapshot, *, sample_col: int = 0, inclusive: bool = True
) -> List[Tuple[int, int]]:
    """Cells outside 上限/下限 rules. Empty if no bound rows or no parseable numbers."""
    rules = _column_limit_rules(
        snap, sample_col=sample_col, inclusive=inclusive
    )
    if not rules:
        return []
    values = snap.values or []
    header_rows, nrows, ncols = _data_region(snap)
    skip_rows = set(find_bound_row_indices(snap, sample_col=sample_col).indices())
    skip_cols = _skip_limit_cols(
        find_bound_row_indices(snap, sample_col=sample_col), sample_col
    )
    flagged: List[Tuple[int, int]] = []
    for c, rule in rules.items():
        if c < 0 or c >= ncols or c in skip_cols:
            continue
        for r in range(header_rows, nrows):
            if r in skip_rows:
                continue
            row = values[r] if r < len(values) else []
            text = row[c] if c < len(row) else ""
            val = parse_numeric_display(text)
            if val is None:
                continue
            if value_violates_limit(val, rule):
                flagged.append((r, c))
    return flagged


def _sheet_a1_range(
    r0: int, c0: int, r1: int, c1: int, *, origin_row: int, origin_col: int
) -> str:
    min_r = origin_row + r0
    min_c = origin_col + c0
    max_r = origin_row + r1
    max_c = origin_col + c1
    return (
        f"{get_column_letter(min_c)}{min_r}:{get_column_letter(max_c)}{max_r}"
    )


def _drop_grid_rows(
    values: List[List[str]],
    merges: List[str],
    drop: set[int],
    *,
    origin_r: int,
) -> tuple[List[List[str]], List[str]]:
    if not drop:
        return values, merges
    new_values = [row for i, row in enumerate(values) if i not in drop]
    new_merges: List[str] = []
    for merge in merges:
        try:
            min_c, min_r, max_c, max_r = range_boundaries(merge)
        except Exception:
            continue
        r0 = min_r - origin_r
        r1 = max_r - origin_r
        if any(r0 <= d <= r1 for d in drop):
            continue
        r0 -= sum(1 for d in drop if d < r0)
        r1 -= sum(1 for d in drop if d < r1)
        min_r = origin_r + r0
        max_r = origin_r + r1
        new_merges.append(
            f"{get_column_letter(min_c)}{min_r}:{get_column_letter(max_c)}{max_r}"
        )
    return new_values, new_merges


def _span_bound_row(
    values: List[List[str]],
    merges: List[str],
    row_i: int,
    src_col: int,
    *,
    sample_col: int,
    first_data: int,
    skip_cols: set[int],
    ncols: int,
    origin_r: int,
    origin_c: int,
) -> List[str]:
    row = _pad_row(values[row_i], ncols)
    expr = row[src_col] if src_col < len(row) else ""
    if first_data >= ncols:
        return merges
    for c in range(ncols):
        if c in skip_cols:
            continue
        row[c] = expr if c == first_data else ""
    span = _sheet_a1_range(
        row_i,
        first_data,
        row_i,
        ncols - 1,
        origin_row=origin_r,
        origin_col=origin_c,
    )
    return [m for m in merges if m != span] + [span]


def prepare_display_snapshot(
    snap: PreviewSnapshot, *, include_limit_row: bool = True, sample_col: int = 0
) -> PreviewSnapshot:
    """Copy snap for UI/Word: bound rows, single-occupied span, empty cells → '/'.

    Does not mutate the source snapshot or the xlsx on disk.
    """
    values = [list(row) for row in (snap.values or [])]
    merges = list(snap.merges or [])
    origin_r = snap.origin_row or 1
    origin_c = snap.origin_col or 1
    working = PreviewSnapshot(
        sheet_name=snap.sheet_name,
        values=values,
        merges=merges,
        origin_row=origin_r,
        origin_col=origin_c,
    )
    bounds, per_col, ncols = _occupied_column_bounds(
        working, sample_col=sample_col
    )
    bound_rows = bounds.indices()

    if bound_rows:
        for row_i in bound_rows:
            _pad_row(values[row_i], ncols)
        skip_cols = _skip_limit_cols(bounds, sample_col)
        first_data = _first_data_col(bounds, sample_col)
        spanned: set[int] = set()
        if len(per_col) == 1:
            src = next(iter(per_col))
            lo, hi = per_col[src]
            if hi is not None and bounds.upper is not None:
                merges = _span_bound_row(
                    values,
                    merges,
                    bounds.upper,
                    src,
                    sample_col=sample_col,
                    first_data=first_data,
                    skip_cols=skip_cols,
                    ncols=ncols,
                    origin_r=origin_r,
                    origin_c=origin_c,
                )
                spanned.add(bounds.upper)
            if lo is not None and bounds.lower is not None:
                merges = _span_bound_row(
                    values,
                    merges,
                    bounds.lower,
                    src,
                    sample_col=sample_col,
                    first_data=first_data,
                    skip_cols=skip_cols,
                    ncols=ncols,
                    origin_r=origin_r,
                    origin_c=origin_c,
                )
                spanned.add(bounds.lower)
        for row_i in bound_rows:
            if row_i in spanned:
                continue
            row = values[row_i]
            for c in range(ncols):
                if c in skip_cols:
                    continue
                if not (row[c] if c < len(row) else "").strip():
                    row[c] = EMPTY_LIMIT_DISPLAY
        if not include_limit_row:
            values, merges = _drop_grid_rows(
                values, merges, set(bound_rows), origin_r=origin_r
            )

    return PreviewSnapshot(
        sheet_name=snap.sheet_name,
        values=values,
        merges=merges,
        origin_row=origin_r,
        origin_col=origin_c,
    )


def _data_region(snap: PreviewSnapshot) -> tuple[int, int, int]:
    """Return (header_rows, nrows, ncols) for the preview grid."""
    values = snap.values or []
    nrows = len(values)
    ncols = max((len(r) for r in values), default=0)
    header_rows = infer_header_row_count(snap) if values else 0
    first_bound = min(find_bound_row_indices(snap).indices(), default=None)
    if first_bound is not None and first_bound < header_rows:
        # Bound rows must not count as repeating Word header.
        header_rows = first_bound
    return header_rows, nrows, ncols


def find_decimal_inconsistencies(
    snap: PreviewSnapshot, *, sample_col: int = 0
) -> List[Tuple[int, int]]:
    """Cells (r,c) whose decimal places differ from the column mode.

    Skips sample column, header rows, empty/non-numeric cells. Compares preview
    display strings as-is (text-filled Excel cells).
    """
    values = snap.values or []
    header_rows, nrows, ncols = _data_region(snap)
    skip_rows = set(find_bound_row_indices(snap, sample_col=sample_col).indices())
    flagged: List[Tuple[int, int]] = []
    for c in range(ncols):
        if c == sample_col:
            continue
        places_by_row: List[Tuple[int, int]] = []
        for r in range(header_rows, nrows):
            if r in skip_rows:
                continue
            row = values[r] if r < len(values) else []
            text = row[c] if c < len(row) else ""
            places = decimal_places(text)
            if places is None:
                continue
            places_by_row.append((r, places))
        if len(places_by_row) < 2:
            continue
        counts: dict[int, int] = {}
        for _, p in places_by_row:
            counts[p] = counts.get(p, 0) + 1
        if len(counts) < 2:
            continue
        mode = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        for r, p in places_by_row:
            if p != mode:
                flagged.append((r, c))
    return flagged


def find_out_of_range(
    snap: PreviewSnapshot,
    lo: float,
    hi: float,
    *,
    col: int | None = None,
    sample_col: int = 0,
) -> List[Tuple[int, int]]:
    """Cells (r,c) whose numeric display value is outside [lo, hi].

    Skips sample column, header rows, empty/non-numeric. If ``col`` is set, only
    that column is checked (still skips sample_col).
    """
    if lo > hi:
        lo, hi = hi, lo
    values = snap.values or []
    header_rows, nrows, ncols = _data_region(snap)
    skip_rows = set(find_bound_row_indices(snap, sample_col=sample_col).indices())
    cols = range(ncols) if col is None else [col]
    flagged: List[Tuple[int, int]] = []
    for c in cols:
        if c == sample_col or c < 0 or c >= ncols:
            continue
        for r in range(header_rows, nrows):
            if r in skip_rows:
                continue
            row = values[r] if r < len(values) else []
            text = row[c] if c < len(row) else ""
            val = parse_numeric_display(text)
            if val is None:
                continue
            if val < lo or val > hi:
                flagged.append((r, c))
    return flagged


def read_preview_snapshot(path: Path) -> PreviewSnapshot:
    """Read first sheet as a nonempty bounding box; keep holes; list intersecting merges."""
    xlsx = Path(path)
    if not xlsx.is_file():
        raise DataTableError("数据表文件不存在")
    wb = load_workbook(xlsx, data_only=False)
    try:
        ws = wb.worksheets[0]
        sheet_name = ws.title or ""
        bbox = _used_bbox(ws)
        if bbox is None:
            return PreviewSnapshot(sheet_name=sheet_name, values=[], merges=[])
        min_r, min_c, max_r, max_c = bbox
        values: List[List[str]] = []
        for r in range(min_r, max_r + 1):
            row_vals: List[str] = []
            for c in range(min_c, max_c + 1):
                row_vals.append(_cell_display(ws.cell(r, c).value))
            values.append(row_vals)
        merges = _merges_in_bbox(ws.merged_cells.ranges, min_r, min_c, max_r, max_c)
        return PreviewSnapshot(
            sheet_name=sheet_name,
            values=values,
            merges=merges,
            origin_row=min_r,
            origin_col=min_c,
        )
    finally:
        wb.close()


def resolve_attachment_path(project_root: Path, ref: DataTableRef) -> Path:
    return Path(project_root) / ref.relative_path


def delete_attachment(path: Path) -> None:
    """Remove the xlsx from disk if present. Missing file is a no-op."""
    target = Path(path)
    if target.is_file():
        target.unlink()


def _snapshot_col_count(snap: PreviewSnapshot) -> int:
    return max((len(r) for r in (snap.values or [])), default=0)


def content_column_groups(
    snap: PreviewSnapshot, *, sample_col: int = 0
) -> List[List[int]]:
    """Partition content columns into unsplittable groups via horizontal merges.

    Sample column is excluded. Columns linked by a horizontal merge stay in one
    group (e.g. -40°C spanning 9V/14V/16V). Unmerged columns are singletons.
    Groups are ordered left-to-right.
    """
    n_cols = _snapshot_col_count(snap)
    content = [c for c in range(n_cols) if c != sample_col]
    if not content:
        return []

    parent = {c: c for c in content}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    origin_r = snap.origin_row or 1
    origin_c = snap.origin_col or 1
    for merge in snap.merges or []:
        try:
            min_c, min_r, max_c, max_r = range_boundaries(merge)
        except Exception:
            continue
        c0 = min_c - origin_c
        c1 = max_c - origin_c
        if c1 <= c0:
            continue
        linked = [c for c in range(c0, c1 + 1) if c in parent]
        for a, b in zip(linked, linked[1:]):
            union(a, b)

    groups: List[List[int]] = []
    seen_roots: set[int] = set()
    for c in content:
        root = find(c)
        if root in seen_roots:
            continue
        members = sorted(x for x in content if find(x) == root)
        if c != members[0]:
            continue
        seen_roots.add(root)
        groups.append(members)
    return groups


def slice_preview_snapshot(
    snap: PreviewSnapshot, cols: Sequence[int]
) -> PreviewSnapshot:
    """Keep only the given 0-based columns (order preserved); remap merges."""
    col_list = [int(c) for c in cols]
    col_map = {old: new for new, old in enumerate(col_list)}
    values: List[List[str]] = []
    for row in snap.values or []:
        values.append([(row[c] if c < len(row) else "") for c in col_list])

    origin_r = snap.origin_row or 1
    origin_c = snap.origin_col or 1
    new_merges: List[str] = []
    for merge in snap.merges or []:
        try:
            min_c, min_r, max_c, max_r = range_boundaries(merge)
        except Exception:
            continue
        c0 = min_c - origin_c
        c1 = max_c - origin_c
        r0 = min_r - origin_r
        r1 = max_r - origin_r
        needed = list(range(c0, c1 + 1))
        if any(c not in col_map for c in needed):
            continue
        mapped = [col_map[c] for c in needed]
        nc0, nc1 = min(mapped), max(mapped)
        # New snapshot is always origin (1,1)
        start = f"{get_column_letter(nc0 + 1)}{r0 + 1}"
        end = f"{get_column_letter(nc1 + 1)}{r1 + 1}"
        if start == end:
            continue
        new_merges.append(f"{start}:{end}")

    return PreviewSnapshot(
        sheet_name=snap.sheet_name,
        values=values,
        merges=new_merges,
        origin_row=1,
        origin_col=1,
    )


def pack_content_column_groups(
    groups: Sequence[Sequence[int]], max_content_cols: int
) -> List[List[int]]:
    """Greedy pack unsplittable groups into chunks of at most max_content_cols.

    A single group larger than the budget is still emitted alone (cannot split).
    """
    limit = max(1, int(max_content_cols))
    chunks: List[List[int]] = []
    current: List[int] = []
    current_n = 0
    for group in groups:
        members = [int(c) for c in group]
        g_n = len(members)
        if not members:
            continue
        if current and current_n + g_n > limit:
            chunks.append(current)
            current = []
            current_n = 0
        current.extend(members)
        current_n += g_n
    if current:
        chunks.append(current)
    return chunks


def split_preview_snapshot_for_page(
    snap: PreviewSnapshot,
    *,
    max_content_cols: int,
    sample_col: int = 0,
) -> List[PreviewSnapshot]:
    """Split a wide snapshot into page-fitting chunks; repeat sample_col each time.

    Column groups follow horizontal merges so header blocks (e.g. temperature
    spans) are not broken across tables when possible.
    """
    n_cols = _snapshot_col_count(snap)
    if n_cols <= 0 or not snap.values:
        return []
    if sample_col < 0 or sample_col >= n_cols:
        sample_col = 0

    groups = content_column_groups(snap, sample_col=sample_col)
    if not groups:
        return [slice_preview_snapshot(snap, [sample_col])]

    content_n = sum(len(g) for g in groups)
    if content_n <= max(1, int(max_content_cols)):
        cols = [sample_col] + [c for g in groups for c in g]
        return [slice_preview_snapshot(snap, cols)]

    chunks = pack_content_column_groups(groups, max_content_cols)
    out: List[PreviewSnapshot] = []
    for content_cols in chunks:
        out.append(slice_preview_snapshot(snap, [sample_col, *content_cols]))
    return out or [snap]
