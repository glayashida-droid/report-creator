"""Note images and Excel tables under a test directory, apart from albums and 数据表附件."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from src.io.data_tables import (
    DataTableError,
    rewrite_test_dir_in_relative_path,
    sanitize_filename_stem,
    unique_xlsx_path,
)
from src.io.test_photos import (
    NOTE_IMAGE_DIR,
    NOTE_TABLE_DIR,
    PhotoError,
    apply_photo_order,
    copy_into_album_keep_names,
    is_image_file,
    is_usable_test_name,
    rename_photo,
    require_leg_name,
    require_usable_test_name,
    test_dir,
)
from src.models.project_state import DataTableRef, TestNode


def note_image_dir(project_root: Path, leg_name: str, test_name: str) -> Path:
    return test_dir(project_root, leg_name, test_name) / NOTE_IMAGE_DIR


def note_table_dir(project_root: Path, leg_name: str, test_name: str) -> Path:
    return test_dir(project_root, leg_name, test_name) / NOTE_TABLE_DIR


def _roots(*candidates: Optional[Path]) -> List[Path]:
    out: List[Path] = []
    for raw in candidates:
        if raw is None:
            continue
        path = Path(raw)
        if path not in out:
            out.append(path)
    return out


def list_note_image_paths(
    local_root: Optional[Path],
    remote_root: Optional[Path],
    leg_name: str,
    test_name: str,
    order: Optional[Sequence[str]] = None,
) -> List[Path]:
    """Local file wins when the same name exists on both sides."""
    if not (leg_name or "").strip() or not is_usable_test_name(test_name):
        return []
    folders: List[Path] = []
    names: List[str] = []
    seen = set()
    for root in _roots(local_root, remote_root):
        folder = note_image_dir(root, leg_name, test_name)
        if not folder.is_dir():
            continue
        folders.append(folder)
        for path in folder.iterdir():
            if is_image_file(path) and path.name not in seen:
                seen.add(path.name)
                names.append(path.name)
    ordered = apply_photo_order(names, order)
    out: List[Path] = []
    for name in ordered:
        for folder in folders:
            candidate = folder / name
            if candidate.is_file():
                out.append(candidate)
                break
    return out


def add_note_images(
    project_root: Path,
    leg_name: str,
    test_name: str,
    sources: Sequence[Path],
) -> List[Path]:
    leg = require_leg_name(leg_name)
    test = require_usable_test_name(test_name)
    folder = note_image_dir(project_root, leg, test)
    return copy_into_album_keep_names(folder, sources)


def rename_note_image(
    local_root: Optional[Path],
    remote_root: Optional[Path],
    leg_name: str,
    test_name: str,
    old_name: str,
    new_name: str,
) -> str:
    """Rename the image on every root that has it. Returns the new filename."""
    old = Path(old_name or "").name
    if not old:
        raise PhotoError("找不到图片")
    renamed = ""
    found = False
    for root in _roots(local_root, remote_root):
        src = note_image_dir(root, leg_name, test_name) / old
        if not src.is_file():
            continue
        found = True
        dest = rename_photo(src, new_name)
        renamed = dest.name
    if not found:
        raise PhotoError("找不到图片")
    return renamed or old


def delete_note_image(
    local_root: Optional[Path],
    remote_root: Optional[Path],
    leg_name: str,
    test_name: str,
    name: str,
) -> None:
    filename = Path(name or "").name
    if not filename:
        return
    for root in _roots(local_root, remote_root):
        path = note_image_dir(root, leg_name, test_name) / filename
        if path.is_file():
            path.unlink()


def list_note_table_refs(
    project_root: Path, leg_name: str, test_name: str
) -> List[DataTableRef]:
    try:
        leg = require_leg_name(leg_name)
        test = require_usable_test_name(test_name)
    except PhotoError:
        return []
    folder = note_table_dir(project_root, leg, test)
    if not folder.is_dir():
        return []
    root = Path(project_root)
    refs: List[DataTableRef] = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or path.suffix.lower() != ".xlsx":
            continue
        if path.name.startswith("~$"):
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        refs.append(DataTableRef(title=path.stem, relative_path=rel))
    return refs


def list_merged_note_table_refs(
    local_root: Optional[Path],
    remote_root: Optional[Path],
    leg_name: str,
    test_name: str,
    preferred: Optional[Sequence[str]] = None,
) -> List[DataTableRef]:
    """Union of 备注表格 refs. Local title wins. ``preferred`` relative paths stay first."""
    by_rel: dict[str, DataTableRef] = {}
    remote = Path(remote_root) if remote_root else None
    local = Path(local_root) if local_root else None
    if remote is not None and remote.is_dir():
        for ref in list_note_table_refs(remote, leg_name, test_name):
            by_rel[ref.relative_path] = ref
    if local is not None and local.is_dir():
        for ref in list_note_table_refs(local, leg_name, test_name):
            by_rel[ref.relative_path] = ref
    preferred_rels = [str(item).replace("\\", "/") for item in (preferred or []) if str(item).strip()]
    ordered: List[DataTableRef] = []
    seen = set()
    for rel in preferred_rels:
        ref = by_rel.get(rel)
        if ref is None or rel in seen:
            continue
        ordered.append(ref)
        seen.add(rel)
    rest = [ref for rel, ref in by_rel.items() if rel not in seen]
    rest.sort(key=lambda ref: (ref.title or "").casefold())
    ordered.extend(rest)
    return ordered


def create_note_workbook(
    project_root: Path, leg_name: str, test_name: str, title: str
) -> DataTableRef:
    """Blank xlsx in 备注表格/. The title is the filename only; reports do not print it."""
    from openpyxl import Workbook

    leg = require_leg_name(leg_name)
    test = require_usable_test_name(test_name)
    name = (title or "").strip()
    if not name:
        raise DataTableError("请输入表格名称")
    folder = note_table_dir(project_root, leg, test)
    stem = sanitize_filename_stem(name)
    dest = unique_xlsx_path(folder, stem)
    wb = Workbook()
    wb.save(dest)
    wb.close()
    rel = dest.relative_to(Path(project_root)).as_posix()
    return DataTableRef(title=name, relative_path=rel)


def delete_note_table(
    local_root: Optional[Path],
    remote_root: Optional[Path],
    relative_path: str,
) -> None:
    rel = Path(str(relative_path or "").replace("\\", "/"))
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise DataTableError("备注表格路径不合法")
    for root in _roots(local_root, remote_root):
        path = root / rel
        if path.is_file():
            path.unlink()


def retarget_node_note_tables(node: TestNode, old_dir_key: str, new_dir_key: str) -> None:
    """Update note_tables relative_path prefixes after a trial folder rename."""
    refs = list(getattr(node, "note_tables", None) or [])
    if not refs:
        return
    node.note_tables = [
        DataTableRef(
            title=ref.title,
            relative_path=rewrite_test_dir_in_relative_path(
                ref.relative_path, old_dir_key, new_dir_key
            ),
        )
        for ref in refs
    ]
