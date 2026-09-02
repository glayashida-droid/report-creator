"""Merge local + remote project photo assets (albums, paths, thumbs, cloud flag)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Union

from PIL import Image

from src.io.test_photos import (
    IMAGE_EXTS,
    SPARE_DIR_NAME,
    album_dir,
    apply_album_order,
    is_image_file,
    is_usable_test_name,
    test_dir,
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
