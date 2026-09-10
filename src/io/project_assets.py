"""Merge local + remote project photo assets (albums, paths, thumbs, cloud flag)."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from PIL import Image

from src.io.data_tables import list_attachment_refs
from src.io.test_photos import (
    IMAGE_EXTS,
    SPARE_ALBUM_NAME,
    SPARE_DIR_NAME,
    TEST_GROUP_DIR,
    PhotoError,
    _rename_path,
    album_dir,
    apply_album_order,
    canonical_image_suffix,
    is_image_file,
    is_usable_test_name,
    numbered_name,
    photo_sort_key,
    photo_stem_key,
    planned_photo_name,
    require_leg_name,
    require_usable_test_name,
    stem_occupied,
    test_dir,
    unique_dest_name,
    validate_album_name,
)
from src.models.project_state import DataTableRef

PathLike = Union[str, Path]

THUMBS_DIR_NAME = ".thumbs"
DEFAULT_THUMB_SIZE = 96


@dataclass(frozen=True)
class MergedPhoto:
    relative_path: str
    read_path: Path
    is_cloud_only: bool


def _as_root(root: Optional[PathLike]) -> Optional[Path]:
    if root is None:
        return None
    path = Path(root)
    return path if str(path).strip() else None


def _album_relative(leg_name: str, test_name: str, album_name: str, filename: str) -> str:
    return (
        album_dir(Path("."), leg_name, test_name, album_name) / filename
    ).as_posix()


def spare_dir(project_root: PathLike, leg_name: str, test_name: str) -> Path:
    return test_dir(project_root, leg_name, test_name) / SPARE_ALBUM_NAME


def resolve_spare_folder_to_open(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
) -> Tuple[Optional[Path], str]:
    """Prefer reachable 公盘 备用/; fall back to local (creating the folder if needed)."""
    local = _as_root(local_root)
    remote = _as_root(remote_root)
    if remote is not None and remote.is_dir():
        folder = spare_dir(remote, leg_name, test_name)
        folder.mkdir(parents=True, exist_ok=True)
        return folder, "remote"
    if local is not None:
        folder = spare_dir(local, leg_name, test_name)
        folder.mkdir(parents=True, exist_ok=True)
        return folder, "local"
    return None, "none"


def _spare_relative_for_photo(relative_path: str) -> str:
    """Map formal-album relative path → same trial's 备用/<filename>."""
    parts = Path(relative_path).parts
    if len(parts) < 4:
        raise PhotoError("照片路径不合法")
    if parts[-2] == SPARE_DIR_NAME:
        raise PhotoError("照片已在备用中")
    return (Path(*parts[:-2]) / SPARE_DIR_NAME / parts[-1]).as_posix()


def _move_into_dir(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_dest_name(dest_dir, src.name)
    shutil.move(str(src), str(dest))
    return dest


def move_photo_to_spare(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    relative_path: str,
) -> Path:
    """Move a formal-album photo into 备用/ on each root where the file exists.

    Returns the last moved spare path (preferring local when both moved).
    """
    rel = Path(relative_path)
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise PhotoError("照片路径不合法")
    spare_rel = _spare_relative_for_photo(relative_path)
    moved: Optional[Path] = None
    local_moved: Optional[Path] = None
    local = _as_root(local_root)
    for root in (local, _as_root(remote_root)):
        if root is None:
            continue
        src = root / rel
        if not src.is_file():
            continue
        dest = _move_into_dir(src, (root / spare_rel).parent)
        moved = dest
        if local is not None and root.resolve() == local.resolve():
            local_moved = dest
    if moved is None:
        raise PhotoError("找不到照片")
    if local is not None:
        dropped = [Path(relative_path).as_posix(), Path(spare_rel).as_posix()]
        if local_moved is not None:
            try:
                dropped.append(local_moved.relative_to(local).as_posix())
            except ValueError:
                pass
        invalidate_photo_thumbs(local, dropped)
    return local_moved or moved


def restore_photo_from_spare(
    project_root: PathLike,
    leg_name: str,
    test_name: str,
    filename: str,
    dest_album: str,
) -> Path:
    """Move a file from 备用/ back into a formal album folder."""
    root = Path(project_root)
    leg = require_leg_name(leg_name)
    test = require_usable_test_name(test_name)
    album = validate_album_name(dest_album)
    if album == SPARE_ALBUM_NAME:
        raise PhotoError("不能还原到备用本身")
    name = Path(filename).name
    if not name or name in {".", ".."}:
        raise PhotoError("文件名不合法")
    src = spare_dir(root, leg, test) / name
    if not src.is_file():
        raise PhotoError(f"备用中找不到：{name}")
    spare_rel = src.relative_to(root).as_posix()
    dest = _move_into_dir(src, album_dir(root, leg, test, album))
    try:
        dest_rel = dest.relative_to(root).as_posix()
    except ValueError:
        dest_rel = ""
    invalidate_photo_thumbs(root, [spare_rel, dest_rel])
    return dest


def _list_image_names(folder: Path) -> List[str]:
    if not folder.is_dir():
        return []
    names = [p.name for p in folder.iterdir() if is_image_file(p)]
    names.sort(key=lambda n: n.casefold())
    return names


def _file_digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.digest()


def _same_photo_payload(left: Path, right: Path) -> bool:
    """True when both files look like the same synced copy (size + hash)."""
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
    except OSError:
        return False
    try:
        return _file_digest(left) == _file_digest(right)
    except OSError:
        return False


def _stem_taken_in_folders(folders: Sequence[Optional[Path]], stem: str) -> bool:
    key = (stem or "").casefold()
    if not key:
        return False
    for folder in folders:
        if folder is not None and stem_occupied(folder, key):
            return True
    return False


def _next_free_album_name(
    local_folder: Optional[Path],
    remote_folder: Optional[Path],
    album_name: str,
    suffix: str,
) -> str:
    """Pick ``{album}-NNN.ext`` unused on either root (fills gaps from 001)."""
    prefix = (album_name or "").strip() or "photo"
    ext = canonical_image_suffix(suffix)
    folders = [local_folder, remote_folder]
    seq = 1
    while True:
        candidate = numbered_name(prefix, seq, ext)
        if not _stem_taken_in_folders(folders, Path(candidate).stem):
            return candidate
        seq += 1


def reconcile_divergent_album_names(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
    album_name: str,
) -> List[str]:
    """Rename remote files that share a name with local but differ in content.

    Same-name sync copies (identical bytes) are left alone so local-wins merge
    stays one thumbnail. Divergent remote files get a free ``{album}-NNN`` name
    so both appear in the merge view. Returns new remote relative paths.
    """
    album = (album_name or "").strip()
    if not album:
        return []
    if not (leg_name or "").strip() or not is_usable_test_name(test_name):
        return []
    local = _as_root(local_root)
    remote = _as_root(remote_root)
    if local is None or remote is None:
        return []
    local_folder = album_dir(local, leg_name, test_name, album)
    remote_folder = album_dir(remote, leg_name, test_name, album)
    if not local_folder.is_dir() or not remote_folder.is_dir():
        return []

    renamed: List[str] = []
    # Snapshot names — renaming mutates the remote folder mid-loop.
    for name in list(_list_image_names(remote_folder)):
        local_file = local_folder / name
        remote_file = remote_folder / name
        if not local_file.is_file() or not remote_file.is_file():
            continue
        if _same_photo_payload(local_file, remote_file):
            continue
        new_name = _next_free_album_name(
            local_folder, remote_folder, album, remote_file.suffix
        )
        dest = remote_folder / new_name
        if dest.exists():
            continue
        old_rel = _album_relative(leg_name, test_name, album, name)
        new_rel = _album_relative(leg_name, test_name, album, new_name)
        _rename_path(remote_file, dest)
        invalidate_photo_thumbs(local, [old_rel, new_rel])
        renamed.append(new_rel)
    return renamed


def list_merged_albums(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
    order: Optional[Sequence[str]] = None,
) -> List[str]:
    """Union of album folder names under local and remote; excludes 备用."""
    if not (leg_name or "").strip() or not is_usable_test_name(test_name):
        return []
    names: set[str] = set()
    for root in (_as_root(local_root), _as_root(remote_root)):
        if root is None:
            continue
        folder = test_dir(root, leg_name, test_name)
        if not folder.is_dir():
            continue
        for child in folder.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name == SPARE_DIR_NAME:
                continue
            names.add(child.name)
    return apply_album_order(sorted(names), order)


def _merge_photos_in_album(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
    album_name: str,
) -> List[MergedPhoto]:
    album = (album_name or "").strip()
    if not album:
        return []
    if not (leg_name or "").strip() or not is_usable_test_name(test_name):
        return []

    local = _as_root(local_root)
    remote = _as_root(remote_root)
    local_folder = album_dir(local, leg_name, test_name, album) if local else None
    remote_folder = album_dir(remote, leg_name, test_name, album) if remote else None

    names: set[str] = set()
    if local_folder is not None:
        names.update(_list_image_names(local_folder))
    if remote_folder is not None:
        names.update(_list_image_names(remote_folder))

    out: List[MergedPhoto] = []
    for name in sorted(names, key=lambda n: n.casefold()):
        rel = _album_relative(leg_name, test_name, album, name)
        local_file = local_folder / name if local_folder is not None else None
        remote_file = remote_folder / name if remote_folder is not None else None
        if local_file is not None and local_file.is_file():
            out.append(
                MergedPhoto(
                    relative_path=rel,
                    read_path=local_file,
                    is_cloud_only=False,
                )
            )
        elif remote_file is not None and remote_file.is_file():
            out.append(
                MergedPhoto(
                    relative_path=rel,
                    read_path=remote_file,
                    is_cloud_only=True,
                )
            )
    return out


def list_merged_photos(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
    album_name: str,
) -> List[MergedPhoto]:
    """Merge album photos: local wins; remote-only → is_cloud_only.

    Album name ``备用`` always returns empty (formal view excludes spare).
    """
    album = (album_name or "").strip()
    if not album or album == SPARE_DIR_NAME:
        return []
    return _merge_photos_in_album(
        local_root, remote_root, leg_name, test_name, album
    )


def list_merged_spare_photos(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
) -> List[MergedPhoto]:
    """Photos in 备用/ for the recycle-bin preview. Not used by export."""
    return _merge_photos_in_album(
        local_root, remote_root, leg_name, test_name, SPARE_DIR_NAME
    )


def _require_relative(relative_path: str) -> Path:
    rel = Path(relative_path)
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise PhotoError("照片路径不合法")
    return rel


def _iter_existing_roots(
    local_root: Optional[PathLike], remote_root: Optional[PathLike]
):
    for root in (_as_root(local_root), _as_root(remote_root)):
        if root is not None:
            yield root


def _merged_other_stems(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    relative_path: Path,
) -> set[str]:
    current = relative_path.name
    stems: set[str] = set()
    for root in _iter_existing_roots(local_root, remote_root):
        folder = (root / relative_path).parent
        if not folder.is_dir():
            continue
        for name in _list_image_names(folder):
            if name == current:
                continue
            stems.add(photo_stem_key(name))
    return stems


def rename_merged_photo(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    relative_path: str,
    new_name: str,
) -> str:
    """Rename a photo on every root that has it. Returns the new relative path."""
    rel = _require_relative(relative_path)
    if SPARE_DIR_NAME in rel.parts:
        raise PhotoError("不能重命名备用中的照片")
    candidate = planned_photo_name(rel.name, new_name)
    dest_rel = rel.with_name(candidate)
    sources = []
    for root in _iter_existing_roots(local_root, remote_root):
        src = root / rel
        if src.is_file():
            sources.append((root, src))
    if not sources:
        raise PhotoError("找不到照片")
    if candidate == rel.name:
        return rel.as_posix()
    if photo_stem_key(candidate) in _merged_other_stems(
        local_root, remote_root, rel
    ):
        raise PhotoError(f"已存在同名文件：{candidate}")
    for root, src in sources:
        dest = root / dest_rel
        try:
            same = dest.exists() and dest.resolve() == src.resolve()
        except OSError:
            same = dest == src
        if dest.exists() and not same:
            raise PhotoError(f"已存在同名文件：{candidate}")
        _rename_path(src, dest)
    return dest_rel.as_posix()


def _rollback_renames(applied: List[Tuple[Path, Path]]) -> None:
    for temp, orig in reversed(applied):
        try:
            if temp.exists() and not orig.exists():
                temp.rename(orig)
        except OSError:
            pass


def renumber_merged_photos(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
    album_name: str,
    ordered_relative_paths: Sequence[str],
    prefix: str,
) -> List[str]:
    """Number merge-view photos as prefix-001… in *ordered_relative_paths* order."""
    album = validate_album_name(album_name)
    if album == SPARE_ALBUM_NAME:
        raise PhotoError("不能重命名备用中的照片")
    photos = list_merged_photos(
        local_root, remote_root, leg_name, test_name, album
    )
    by_rel = {item.relative_path: item for item in photos}
    ordered: List[MergedPhoto] = []
    seen: set[str] = set()
    for raw in ordered_relative_paths:
        key = Path(raw).as_posix()
        item = by_rel.get(key) or by_rel.get(raw)
        if item is None or item.relative_path in seen:
            continue
        ordered.append(item)
        seen.add(item.relative_path)
    for item in photos:
        if item.relative_path not in seen:
            ordered.append(item)
            seen.add(item.relative_path)
    if not ordered:
        return []

    applied: List[Tuple[Path, Path]] = []
    finals: List[Tuple[Path, Path]] = []
    try:
        for index, item in enumerate(ordered):
            rel = Path(item.relative_path)
            suffix = canonical_image_suffix(rel.suffix)
            dest_name = numbered_name(prefix, index + 1, suffix)
            for root in _iter_existing_roots(local_root, remote_root):
                src = root / rel
                if not src.is_file():
                    continue
                temp = src.parent / (
                    f".__renaming_{uuid.uuid4().hex}_{index}{suffix}"
                )
                _rename_path(src, temp)
                applied.append((temp, src))
                finals.append((temp, src.parent / dest_name))
    except PhotoError:
        _rollback_renames(applied)
        raise

    try:
        for temp, dest in finals:
            _rename_path(temp, dest)
    except PhotoError:
        _rollback_renames(applied)
        raise

    new_rels = [
        Path(item.relative_path)
        .with_name(
            numbered_name(
                prefix, index, canonical_image_suffix(Path(item.relative_path).suffix)
            )
        )
        .as_posix()
        for index, item in enumerate(ordered, start=1)
    ]
    invalidate_photo_thumbs(
        local_root,
        [item.relative_path for item in ordered] + new_rels,
    )
    return new_rels


def rename_all_merged_in_album(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
    album_name: str,
    prefix: str,
) -> List[str]:
    """EXIF (else mtime) order, then prefix-001… on local and remote copies."""
    photos = list_merged_photos(
        local_root, remote_root, leg_name, test_name, album_name
    )
    photos = sorted(photos, key=lambda item: photo_sort_key(item.read_path))
    return renumber_merged_photos(
        local_root,
        remote_root,
        leg_name,
        test_name,
        album_name,
        [item.relative_path for item in photos],
        prefix,
    )


def resolve_photo_path(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    relative_path: str,
) -> Optional[Path]:
    """Local file if present, else remote; None if missing on both."""
    return _resolve_project_file(local_root, remote_root, relative_path)


def resolve_data_table_path(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    relative_path: str,
) -> Optional[Path]:
    """Local xlsx if present, else remote; None if missing on both."""
    return _resolve_project_file(local_root, remote_root, relative_path)


def _resolve_project_file(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    relative_path: str,
) -> Optional[Path]:
    rel = Path(relative_path)
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        return None
    local = _as_root(local_root)
    remote = _as_root(remote_root)
    if local is not None:
        candidate = local / rel
        if candidate.is_file():
            return candidate
    if remote is not None:
        candidate = remote / rel
        if candidate.is_file():
            return candidate
    return None


def list_merged_attachment_refs(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
) -> List[DataTableRef]:
    """Union of 数据表附件 refs under local and remote; local title wins on clash."""
    by_rel: dict[str, DataTableRef] = {}
    remote = _as_root(remote_root)
    if remote is not None:
        for ref in list_attachment_refs(remote, leg_name, test_name):
            by_rel[ref.relative_path] = DataTableRef(
                title=ref.title, relative_path=ref.relative_path
            )
    local = _as_root(local_root)
    if local is not None:
        for ref in list_attachment_refs(local, leg_name, test_name):
            by_rel[ref.relative_path] = DataTableRef(
                title=ref.title, relative_path=ref.relative_path
            )
    return sorted(
        by_rel.values(),
        key=lambda r: Path(r.relative_path).name.casefold(),
    )


def download_photo_to_album(
    local_root: PathLike,
    remote_root: Optional[PathLike],
    relative_path: str,
) -> Path:
    """Copy a remote-only photo into the local formal album path.

    If the local file already exists, returns it without copying again.
    """
    rel = Path(relative_path)
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise PhotoError("照片路径不合法")
    if SPARE_DIR_NAME in rel.parts:
        raise PhotoError("不能下载备用中的路径到相册")
    local = Path(local_root)
    dest = local / rel
    if dest.is_file():
        return dest
    remote = _as_root(remote_root)
    if remote is None:
        raise PhotoError("公盘路径不可用")
    src = remote / rel
    if not src.is_file():
        raise PhotoError("公盘上找不到该照片")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


PREVIEW_SIZE = 800


def preview_path_for_photo(
    local_root: PathLike,
    remote_root: Optional[PathLike],
    relative_path: str,
    *,
    size: int = PREVIEW_SIZE,
) -> Path:
    """Medium preview under `.thumbs/` — never writes into formal album dirs."""
    read = resolve_photo_path(local_root, remote_root, relative_path)
    if read is None:
        raise PhotoError("找不到照片")
    return thumbnail_for_photo(local_root, relative_path, read, size=size)


def original_view_path(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    relative_path: str,
) -> Path:
    """Path suitable for viewing the original without writing into album dirs.

    Local file is returned as-is. Cloud-only copies into a temp file.
    """
    rel = Path(relative_path)
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise PhotoError("照片路径不合法")
    local = _as_root(local_root)
    if local is not None:
        candidate = local / rel
        if candidate.is_file():
            return candidate
    remote = _as_root(remote_root)
    if remote is None:
        raise PhotoError("找不到照片")
    src = remote / rel
    if not src.is_file():
        raise PhotoError("找不到照片")
    suffix = src.suffix.lower() or ".jpg"
    fd, name = tempfile.mkstemp(prefix="reach-photo-", suffix=suffix)
    os.close(fd)
    dest = Path(name)
    shutil.copy2(src, dest)
    return dest


def thumbs_dir(local_root: PathLike) -> Path:
    return Path(local_root) / THUMBS_DIR_NAME


def thumbnail_cache_path(
    local_root: PathLike,
    relative_path: str,
    *,
    size: int = DEFAULT_THUMB_SIZE,
) -> Path:
    """Stable cache path under local `.thumbs/` for a project-relative photo."""
    rel = Path(relative_path)
    safe = "__".join(rel.parts)
    stem = Path(safe).stem
    suffix = Path(safe).suffix.lower() or ".jpg"
    if suffix not in IMAGE_EXTS:
        suffix = ".jpg"
    return thumbs_dir(local_root) / f"{stem}_{size}{suffix}"


def invalidate_photo_thumbs(
    local_root: Optional[PathLike], relative_paths: Sequence[str]
) -> None:
    """Drop `.thumbs` files keyed by *relative_paths* (all sizes)."""
    local = _as_root(local_root)
    if local is None:
        return
    folder = thumbs_dir(local)
    if not folder.is_dir():
        return
    prefixes = []
    for raw in relative_paths:
        if not raw:
            continue
        safe = "__".join(Path(raw).parts)
        stem = Path(safe).stem
        if stem:
            prefixes.append(f"{stem}_")
    if not prefixes:
        return
    for path in folder.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if any(name.startswith(prefix) for prefix in prefixes):
            try:
                path.unlink()
            except OSError:
                pass


def invalidate_thumbs_for_files(
    local_root: Optional[PathLike], file_paths: Sequence[PathLike]
) -> None:
    """Drop `.thumbs` files for album files under *local_root*."""
    local = _as_root(local_root)
    if local is None:
        return
    rels: List[str] = []
    try:
        root = local.resolve()
    except OSError:
        return
    for raw in file_paths:
        path = Path(raw)
        try:
            rels.append(path.resolve().relative_to(root).as_posix())
        except (ValueError, OSError):
            continue
    invalidate_photo_thumbs(local, rels)


def invalidate_thumbs_for_album_files(
    album_folder: PathLike, dest_files: Sequence[PathLike]
) -> None:
    """Invalidate thumbs for files copied into an album folder."""
    try:
        album = Path(album_folder).resolve()
    except OSError:
        return
    local_root = None
    for parent in album.parents:
        if parent.name == TEST_GROUP_DIR:
            local_root = parent.parent
            break
    if local_root is None:
        return
    invalidate_thumbs_for_files(local_root, dest_files)


def thumbnail_for_photo(
    local_root: PathLike,
    relative_path: str,
    read_path: PathLike,
    *,
    size: int = DEFAULT_THUMB_SIZE,
) -> Path:
    """Return a cached thumbnail path, generating synchronously if missing."""
    cache = thumbnail_cache_path(local_root, relative_path, size=size)
    src = Path(read_path)
    if cache.is_file():
        try:
            if cache.stat().st_mtime >= src.stat().st_mtime:
                return cache
        except OSError:
            pass
    cache.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
        img.thumbnail((size, size))
        fmt = "JPEG" if cache.suffix.lower() in {".jpg", ".jpeg"} else "PNG"
        save_kwargs = {"quality": 85} if fmt == "JPEG" else {}
        img.save(cache, fmt, **save_kwargs)
    return cache


@dataclass(frozen=True)
class ExportPhoto:
    album: str
    path: Path
    stem: str


def iter_merged_export_photos(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    leg_name: str,
    test_name: str,
    order: Optional[Sequence[str]] = None,
    *,
    temps: Optional[List[Path]] = None,
) -> List[ExportPhoto]:
    """Album-ordered embed paths via merge view; cloud-only materializes to temp.

    Does not write into formal album directories. When ``temps`` is provided,
    cloud temp paths are appended for the caller to delete after export.
    """
    out: List[ExportPhoto] = []
    for album in list_merged_albums(local_root, remote_root, leg_name, test_name, order=order):
        for photo in list_merged_photos(
            local_root, remote_root, leg_name, test_name, album
        ):
            if photo.is_cloud_only:
                path = original_view_path(local_root, remote_root, photo.relative_path)
                if temps is not None:
                    temps.append(path)
            else:
                path = photo.read_path
            out.append(
                ExportPhoto(
                    album=album,
                    path=path,
                    stem=Path(photo.relative_path).stem,
                )
            )
    return out
