"""Merge local + remote project photo assets (albums, paths, thumbs, cloud flag)."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Union

from PIL import Image

from src.io.test_photos import (
    IMAGE_EXTS,
    SPARE_ALBUM_NAME,
    SPARE_DIR_NAME,
    PhotoError,
    album_dir,
    apply_album_order,
    is_image_file,
    is_usable_test_name,
    require_leg_name,
    require_usable_test_name,
    test_dir,
    unique_dest_name,
    validate_album_name,
)

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
    return _move_into_dir(src, album_dir(root, leg, test, album))


def _list_image_names(folder: Path) -> List[str]:
    if not folder.is_dir():
        return []
    names = [p.name for p in folder.iterdir() if is_image_file(p)]
    names.sort(key=lambda n: n.casefold())
    return names


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


def resolve_photo_path(
    local_root: Optional[PathLike],
    remote_root: Optional[PathLike],
    relative_path: str,
) -> Optional[Path]:
    """Local file if present, else remote; None if missing on both."""
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
