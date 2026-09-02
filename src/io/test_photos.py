"""Manage test photos on disk under 3.测试组/{Leg名}-{试验名}/{照片文件夹}/."""

from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from PIL import Image

TEST_GROUP_DIR = "3.测试组"
RENAME_CONFLICT_MESSAGE = "同名试验项目已存在，请重新命名"
TEMPLATE_ALBUMS = ("试验前", "试验中", "数据", "试验后")
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
SPARE_DIR_NAME = "备用"
SPARE_ALBUM_NAME = SPARE_DIR_NAME  # alias — 试验目录下与数据表附件同级
PLACEHOLDER_TEST_NAME = "请选择试验..."
CUSTOM_TEST_NAME = "自定义"
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')
_EXIF_DATETIME = 306
_EXIF_IFD = 0x8769
_EXIF_ORIGINAL = 36867
_EXIF_DIGITIZED = 36868


class PhotoError(Exception):
    pass


def is_usable_test_name(name: str) -> bool:
    text = (name or "").strip()
    return bool(text) and text not in {PLACEHOLDER_TEST_NAME, CUSTOM_TEST_NAME}


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTS and not path.name.startswith(".")


def test_dir_key(leg_name: str, test_name: str) -> str:
    """Directory name under 3.测试组/: {leg_name}-{中文试验名}."""
    return f"{(leg_name or '').strip()}-{(test_name or '').strip()}"


def test_dir(project_root: Path, leg_name: str, test_name: str) -> Path:
    return Path(project_root) / TEST_GROUP_DIR / test_dir_key(leg_name, test_name)


def album_dir(project_root: Path, leg_name: str, test_name: str, album_name: str) -> Path:
    return test_dir(project_root, leg_name, test_name) / (album_name or "").strip()


def require_leg_name(leg_name: str) -> str:
    name = (leg_name or "").strip()
    if not name:
        raise PhotoError("缺少 Leg 名称")
    return name


def require_usable_test_name(test_name: str) -> str:
    name = (test_name or "").strip()
    if not is_usable_test_name(name):
        raise PhotoError("请先选择试验名称")
    return name


def validate_album_name(name: str) -> str:
    text = (name or "").strip()
    if not text or text in {".", ".."} or _BAD_NAME.search(text):
        raise PhotoError("文件夹名称不合法")
    return text


def album_sort_key(name: str) -> Tuple[int, object]:
    try:
        return (0, TEMPLATE_ALBUMS.index(name))
    except ValueError:
        return (1, name.casefold())


def apply_album_order(
    albums: Sequence[str], preferred: Optional[Sequence[str]] = None
) -> List[str]:
    """Order disk albums by preferred names; unknown names keep default sort at the end."""
    present = [a for a in albums if a]
    if not preferred:
        return sorted(present, key=album_sort_key)
    seen = set()
    out: List[str] = []
    for name in preferred:
        text = (name or "").strip()
        if not text or text in seen or text not in present:
            continue
        out.append(text)
        seen.add(text)
    rest = [a for a in present if a not in seen]
    rest.sort(key=album_sort_key)
    out.extend(rest)
    return out


def uses_data_photo_layout(album: str) -> bool:
    """Large single-column embed; locked to the default 「数据」 folder only."""
    return (album or "").strip() == "数据"


def list_albums(
    project_root: Path,
    leg_name: str,
    test_name: str,
    order: Optional[Sequence[str]] = None,
) -> List[str]:
    if not (leg_name or "").strip() or not is_usable_test_name(test_name):
        return []
    root = test_dir(project_root, leg_name, test_name)
    if not root.is_dir():
        return []
    names = [
        p.name
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != SPARE_DIR_NAME
    ]
    return apply_album_order(names, order)


def list_photos(project_root: Path, leg_name: str, test_name: str, album_name: str) -> List[Path]:
    folder = album_dir(project_root, leg_name, test_name, album_name)
    if not folder.is_dir():
        return []
    photos = [p for p in folder.iterdir() if is_image_file(p)]
    photos.sort(key=lambda p: p.name.casefold())
    return photos


def iter_export_photos(
    project_root: Path,
    leg_name: str,
    test_name: str,
    order: Optional[Sequence[str]] = None,
    remote_root: Optional[Path] = None,
    temps: Optional[List[Path]] = None,
) -> List[Path]:
    """Export-ready photo paths via merge view (local + optional remote)."""
    from src.io.project_assets import iter_merged_export_photos

    return [
        item.path
        for item in iter_merged_export_photos(
            project_root,
            remote_root,
            leg_name,
            test_name,
            order=order,
            temps=temps,
        )
    ]


def remap_album_order(
    order: Sequence[str], old_name: str, new_name: str
) -> List[str]:
    """Keep relative position when an album folder is renamed."""
    old = (old_name or "").strip()
    new = (new_name or "").strip()
    out: List[str] = []
    seen = set()
    for name in order or []:
        text = new if (name or "").strip() == old else (name or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    if new and new not in seen:
        out.append(new)
    return out


def create_album(project_root: Path, leg_name: str, test_name: str, album_name: str) -> Path:
    leg = require_leg_name(leg_name)
    test = require_usable_test_name(test_name)
    name = validate_album_name(album_name)
    if name == SPARE_ALBUM_NAME:
        raise PhotoError(f"「{SPARE_ALBUM_NAME}」为系统保留文件夹")
    dest = album_dir(project_root, leg, test, name)
    if dest.exists():
        raise PhotoError(f"文件夹已存在：{name}")
    dest.mkdir(parents=True, exist_ok=False)
    return dest


def create_template_albums(project_root: Path, leg_name: str, test_name: str) -> List[str]:
    leg = require_leg_name(leg_name)
    test = require_usable_test_name(test_name)
    created = []
    for name in TEMPLATE_ALBUMS:
        dest = album_dir(project_root, leg, test, name)
        if dest.exists():
            continue
        dest.mkdir(parents=True, exist_ok=True)
        created.append(name)
    return created


def rename_album(
    project_root: Path, leg_name: str, test_name: str, old_name: str, new_name: str
) -> Path:
    leg = require_leg_name(leg_name)
    test = require_usable_test_name(test_name)
    src_name = validate_album_name(old_name)
    dest_name = validate_album_name(new_name)
    if dest_name == SPARE_ALBUM_NAME:
        raise PhotoError(f"「{SPARE_ALBUM_NAME}」为系统保留文件夹")
    src = album_dir(project_root, leg, test, src_name)
    dest = album_dir(project_root, leg, test, dest_name)
    if src_name == dest_name:
        return src
    if not src.is_dir():
        raise PhotoError(f"找不到文件夹：{src_name}")
    if dest.exists():
        raise PhotoError(f"文件夹已存在：{dest_name}")
    src.rename(dest)
    return dest


def delete_album(project_root: Path, leg_name: str, test_name: str, album_name: str) -> None:
    folder = album_dir(project_root, leg_name, test_name, validate_album_name(album_name))
    if not folder.exists():
        return
    shutil.rmtree(folder)


def delete_photo(path: Path) -> None:
    target = Path(path)
    if target.is_file():
        target.unlink()


def rename_test_dir(project_root: Path, old_key: str, new_key: str) -> Optional[Path]:
    """Rename the 试验目录. Keys are folder names under 3.测试组/ (e.g. Leg 1-高温试验)."""
    old = (old_key or "").strip()
    new = (new_key or "").strip()
    if not old or not new:
        return None
    src = Path(project_root) / TEST_GROUP_DIR / old
    if not src.exists():
        return None
    dest = Path(project_root) / TEST_GROUP_DIR / new
    if src.resolve() == dest.resolve():
        return src
    if dest.exists():
        raise PhotoError(RENAME_CONFLICT_MESSAGE)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    return dest


def hooked_test_dir_key(project_root: Path, leg_name: str, test_name: str) -> Optional[str]:
    """Return the on-disk trial dir key when hooked, else None."""
    if not is_usable_test_name(test_name):
        return None
    key = test_dir_key(leg_name, test_name)
    path = Path(project_root) / TEST_GROUP_DIR / key
    return key if path.is_dir() else None


def delete_test_dir(project_root: Path, dir_key: str) -> None:
    """Remove the entire 试验目录. No-op if missing."""
    key = (dir_key or "").strip()
    if not key:
        return
    path = Path(project_root) / TEST_GROUP_DIR / key
    if path.is_dir():
        shutil.rmtree(path)


def collect_drop_images(paths: Sequence[Path]) -> Tuple[List[Path], List[str]]:
    """Images from files and one-level folders. Nested dirs are ignored."""
    images: List[Path] = []
    skipped: List[str] = []
    seen = set()
    for raw in paths:
        path = Path(raw)
        candidates: Iterable[Path]
        if path.is_dir():
            candidates = sorted(path.iterdir(), key=lambda p: p.name.casefold())
        elif path.is_file():
            candidates = [path]
        else:
            skipped.append(path.name)
            continue
        for item in candidates:
            if item.is_dir():
                continue
            if not is_image_file(item):
                skipped.append(item.name)
                continue
            key = str(item.resolve())
            if key in seen:
                continue
            seen.add(key)
            images.append(item)
    return images, skipped


def next_sequence(folder: Path, prefix: str) -> int:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    highest = 0
    if folder.is_dir():
        for item in folder.iterdir():
            if not is_image_file(item):
                continue
            match = pattern.match(item.stem)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def numbered_name(prefix: str, number: int, suffix: str) -> str:
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    return f"{prefix}-{number:03d}{ext.lower()}"


def unique_dest_name(folder: Path, filename: str) -> Path:
    """Pick folder/filename, or folder/stem_N.ext if that name is taken."""
    dest_dir = Path(folder)
    name = Path(filename).name
    if not name or name in {".", ".."} or _BAD_NAME.search(name):
        raise PhotoError("文件名不合法")
    dest = dest_dir / name
    if not dest.exists():
        return dest
    stem = Path(name).stem
    suffix = Path(name).suffix
    n = 1
    while True:
        candidate = dest_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def copy_into_album(folder: Path, sources: Sequence[Path], prefix: str) -> List[Path]:
    dest_dir = Path(folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    seq = next_sequence(dest_dir, prefix)
    written: List[Path] = []
    for src in sources:
        src = Path(src)
        dest = dest_dir / numbered_name(prefix, seq, src.suffix)
        while dest.exists():
            seq += 1
            dest = dest_dir / numbered_name(prefix, seq, src.suffix)
        shutil.copy2(src, dest)
        written.append(dest)
        seq += 1
    return written


def copy_into_album_keep_names(folder: Path, sources: Sequence[Path]) -> List[Path]:
    """Copy images keeping each source basename; collide → stem_1.ext, stem_2.ext…"""
    dest_dir = Path(folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for src in sources:
        src = Path(src)
        dest = unique_dest_name(dest_dir, src.name)
        shutil.copy2(src, dest)
        written.append(dest)
    return written


def rename_photo(path: Path, new_name: str) -> Path:
    """Rename one image in place. Keeps original suffix if new_name has none."""
    src = Path(path)
    if not src.is_file():
        raise PhotoError("找不到照片")
    text = (new_name or "").strip()
    if not text or text in {".", ".."} or _BAD_NAME.search(text) or "/" in text or "\\" in text:
        raise PhotoError("文件名不合法")
    candidate = Path(text).name
    if not Path(candidate).suffix:
        candidate = f"{candidate}{src.suffix.lower()}"
    elif Path(candidate).suffix.lower() not in IMAGE_EXTS:
        raise PhotoError("只支持 jpg / jpeg / png")
    else:
        stem = Path(candidate).stem
        ext = Path(candidate).suffix.lower()
        candidate = f"{stem}{ext}"
    dest = src.with_name(candidate)
    if dest.resolve() == src.resolve():
        return src
    if dest.exists():
        raise PhotoError(f"已存在同名文件：{candidate}")
    src.rename(dest)
    return dest


def _parse_exif_datetime(value) -> Optional[float]:
    text = str(value or "").strip().split(".")[0]
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return None


def _exif_datetime(path: Path) -> Optional[float]:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            for tag in (_EXIF_ORIGINAL, _EXIF_DIGITIZED, _EXIF_DATETIME):
                parsed = _parse_exif_datetime(exif.get(tag))
                if parsed is not None:
                    return parsed
            try:
                ifd = exif.get_ifd(_EXIF_IFD)
            except Exception:
                ifd = None
            if ifd:
                for tag in (_EXIF_ORIGINAL, _EXIF_DIGITIZED, _EXIF_DATETIME):
                    parsed = _parse_exif_datetime(ifd.get(tag))
                    if parsed is not None:
                        return parsed
    except Exception:
        return None
    return None


def photo_sort_key(path: Path) -> Tuple[float, str]:
    stamp = _exif_datetime(path)
    if stamp is None:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            stamp = 0.0
    return (stamp, path.name.casefold())


def rename_all_in_album(folder: Path, prefix: str) -> List[Path]:
    dest_dir = Path(folder)
    if not dest_dir.is_dir():
        raise PhotoError("找不到照片文件夹")
    photos = [p for p in dest_dir.iterdir() if is_image_file(p)]
    photos.sort(key=photo_sort_key)
    temps = []
    for index, src in enumerate(photos):
        temp = dest_dir / f".__renaming_{uuid.uuid4().hex}_{index}{src.suffix.lower()}"
        src.rename(temp)
        temps.append(temp)
    written: List[Path] = []
    for index, temp in enumerate(temps, start=1):
        dest = dest_dir / numbered_name(prefix, index, temp.suffix)
        temp.rename(dest)
        written.append(dest)
    return written
