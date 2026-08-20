"""Manage data-table xlsx attachments under 3.测试组/{试验名}/数据表附件/."""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook

from src.io.test_photos import is_usable_test_name, test_dir
from src.models.project_state import DataTableRef

ATTACHMENT_DIR = "数据表附件"
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')


class DataTableError(Exception):
    pass


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
