"""Copy a project folder into the local data/ mirror and list saved sessions."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from src.io.test_photos import IMAGE_EXTS

SKIP_FILE_NAMES = {".DS_Store", "Thumbs.db", "project_state.json"}
SKIP_DIR_NAMES = {".DS_Store"}

# Structure mirror keeps a directory skeleton + light files only.
# Photos and oversized attachments stay on the remote until explicit download / upload.
STRUCTURE_MIRROR_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MiB


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_data_root() -> Path:
    return repo_root() / "data"


def local_project_dir(project_id: str, data_root: Optional[Path] = None) -> Path:
    return (data_root or default_data_root()) / project_id


def state_file_path(project_id: str, data_root: Optional[Path] = None) -> Path:
    return local_project_dir(project_id, data_root) / "project_state.json"


def should_skip_file(name: str) -> bool:
    if name in SKIP_FILE_NAMES:
        return True
    if name.startswith("~$"):
        return True
    return False


def is_structure_mirror_skipped(
    path: Path,
    *,
    max_bytes: int = STRUCTURE_MIRROR_MAX_FILE_BYTES,
) -> bool:
    """True when structure mirror should not copy this file (image or oversized)."""
    if path.suffix.lower() in IMAGE_EXTS:
        return True
    try:
        return path.stat().st_size > max_bytes
    except OSError:
        return True


def _needs_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    try:
        src_stat = src.stat()
        dst_stat = dst.stat()
    except OSError:
        return True
    if src_stat.st_size != dst_stat.st_size:
        return True
    if src_stat.st_mtime > dst_stat.st_mtime + 2:
        return True
    return False


def incremental_copy(
    src: Path,
    dest: Path,
    cancelled: Optional[Callable[[], bool]] = None,
    *,
    structure_only: bool = True,
) -> bool:
    """Copy src into dest as a structure mirror (dirs + light files).

    By default skips IMAGE_EXTS originals and files larger than
    STRUCTURE_MIRROR_MAX_FILE_BYTES, while still creating every walked
    directory so the local skeleton remains. Always skips junk, ``~$``,
    and never overwrites local project_state.json from the source tree.

    Returns False if cancelled mid-copy.
    """
    src = Path(src)
    dest = Path(dest)
    if not src.is_dir():
        raise NotADirectoryError(str(src))
    dest.mkdir(parents=True, exist_ok=True)

    for dirpath, dirnames, filenames in os.walk(src):
        if cancelled and cancelled():
            return False
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        rel = Path(dirpath).relative_to(src)
        target_dir = dest / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            if cancelled and cancelled():
                return False
            if should_skip_file(name):
                continue
            src_file = Path(dirpath) / name
            if not src_file.is_file():
                continue
            if structure_only and is_structure_mirror_skipped(src_file):
                continue
            dst_file = target_dir / name
            if not _needs_copy(src_file, dst_file):
                continue
            shutil.copy2(src_file, dst_file)
    return True


@dataclass
class SavedProject:
    project_id: str
    json_path: Path
    local_path: Path
    applicant_name: str
    sample_name: str
    saved_at: float


def list_saved_projects(data_root: Optional[Path] = None) -> List[SavedProject]:
    root = data_root or default_data_root()
    if not root.is_dir():
        return []
    found: List[SavedProject] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        json_path = child / "project_state.json"
        if not json_path.is_file():
            continue
        applicant = ""
        sample = ""
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            applicant = str(data.get("applicant_name") or "").strip()
            sample = str(data.get("sample_name") or "").strip()
            project_id = str(data.get("project_id") or "").strip() or child.name
        except (OSError, json.JSONDecodeError, TypeError):
            project_id = child.name
        try:
            saved_at = json_path.stat().st_mtime
        except OSError:
            saved_at = 0.0
        found.append(
            SavedProject(
                project_id=project_id,
                json_path=json_path,
                local_path=child,
                applicant_name=applicant,
                sample_name=sample,
                saved_at=saved_at,
            )
        )
    found.sort(key=lambda p: p.saved_at, reverse=True)
    return found
