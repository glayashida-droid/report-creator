"""Manage data-table xlsx attachments under 3.测试组/{试验名}/数据表附件/."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

from openpyxl import Workbook, load_workbook

from src.io.project_mirror import repo_root
from src.io.test_photos import is_usable_test_name, test_dir
from src.models.project_state import DataTableRef

ATTACHMENT_DIR = "数据表附件"
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')

# macOS .app bundle names / Windows executable stems, preferred order
_EXCEL_APP_NAMES = ("Microsoft Excel",)
_WPS_APP_NAMES = ("wpsoffice", "WPS Office", "kingsoft")


def default_templates_dir() -> Path:
    return repo_root() / "templates" / "data_tables"


class DataTableError(Exception):
    pass


@dataclass
class PreviewSnapshot:
    """Readonly first-sheet bbox: values as strings, empty cells kept, merges as A1:B2."""

    sheet_name: str
    values: List[List[str]] = field(default_factory=list)
    merges: List[str] = field(default_factory=list)
    # 1-based origin of values[0][0] in the sheet (for mapping merge refs onto the grid)
    origin_row: int = 1
    origin_col: int = 1


def attachment_dir(project_root: Path, test_name: str) -> Path:
    return test_dir(project_root, test_name) / ATTACHMENT_DIR


def _require_usable_test_name(test_name: str) -> str:
    name = (test_name or "").strip()
    if not is_usable_test_name(name):
        raise DataTableError("请先选择试验名称")
    return name


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
    project_root: Path, test_name: str, title: str
) -> DataTableRef:
    """Create an empty xlsx in the attachment folder; return an index ref."""
    test = _require_usable_test_name(test_name)
    name = (title or "").strip()
    if not name:
        raise DataTableError("请输入数据表标题")
    folder = attachment_dir(project_root, test)
    stem = sanitize_filename_stem(name)
    dest = unique_xlsx_path(folder, stem)
    wb = Workbook()
    wb.save(dest)
    wb.close()
    rel = dest.relative_to(Path(project_root)).as_posix()
    return DataTableRef(title=name, relative_path=rel)


def upload_existing_xlsx(
    project_root: Path, test_name: str, source: Path
) -> DataTableRef:
    """Copy an existing .xlsx into the attachment folder; title is the filename."""
    test = _require_usable_test_name(test_name)
    src = Path(source)
    if not src.is_file():
        raise DataTableError("找不到所选 Excel 文件")
    if src.suffix.lower() != ".xlsx":
        raise DataTableError("仅支持 .xlsx 文件")
    folder = attachment_dir(project_root, test)
    stem = sanitize_filename_stem(src.stem)
    dest = unique_xlsx_path(folder, stem)
    shutil.copy2(src, dest)
    title = src.name
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
    project_root: Path, test_name: str, template_path: Path
) -> DataTableRef:
    """Copy a template .xlsx into the attachment folder (same semantics as upload)."""
    return upload_existing_xlsx(project_root, test_name, template_path)


def _col1_has_content(ws) -> bool:
    for row in ws.iter_rows(min_col=1, max_col=1):
        for cell in row:
            if _is_nonempty(cell.value):
                return True
    return False


def import_sample_ids(path: Path, sample_ids: Sequence[str]) -> None:
    """Write sample ids into the first sheet from row 2; insert col 1 if it has content."""
    xlsx = Path(path)
    if not xlsx.is_file():
        raise DataTableError("数据表文件不存在")
    ids = [str(s).strip() for s in sample_ids if str(s).strip()]
    wb = load_workbook(xlsx)
    try:
        ws = wb.worksheets[0]
        if _col1_has_content(ws):
            ws.insert_cols(1)
        for i, sid in enumerate(ids):
            ws.cell(row=2 + i, column=1, value=sid)
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
