"""Project sync — JSON remote lifecycle + nightly upload / purge."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Union

from src.io.project_mirror import (
    STRUCTURE_MIRROR_MAX_FILE_BYTES,
    SKIP_DIR_NAMES,
    should_skip_file,
)
from src.io.test_photos import IMAGE_EXTS
from src.models.project_state import ProjectState

PathLike = Union[str, Path]
PROJECT_STATE_NAME = "project_state.json"
PENDING_REMOTE_JSON_NAME = ".pending_remote_json"
THUMBS_DIR_NAME = ".thumbs"
# Nightly purge targets: images, spreadsheets, or oversized (aligned with TKT-2 + xlsx).
_PURGE_EXTS = IMAGE_EXTS | {".xlsx", ".xls"}


class RemoteJsonError(OSError):
    """Raised when project_state.json cannot be written to the remote root."""


@dataclass
class UploadFailure:
    relative_path: str
    error: str


@dataclass
class SyncReport:
    uploaded: List[str] = field(default_factory=list)
    purged: List[str] = field(default_factory=list)
    failed: List[UploadFailure] = field(default_factory=list)

    @property
    def ok_paths(self) -> List[str]:
        return list(self.uploaded)


def remote_state_path(remote_root: PathLike) -> Path:
    return Path(remote_root) / PROJECT_STATE_NAME


def local_state_path(local_root: PathLike) -> Path:
    return Path(local_root) / PROJECT_STATE_NAME


def load_json_from_remote(remote_root: PathLike) -> Optional[ProjectState]:
    """Load project_state.json from the remote project root.

    Returns None when the file is missing or unreadable.
    """
    path = remote_state_path(remote_root)
    if not path.is_file():
        return None
    try:
        return ProjectState.load_from_file(str(path))
    except (OSError, ValueError, TypeError):
        return None


def is_remote_json_newer(local_root: PathLike, remote_root: PathLike) -> bool:
    """True when remote project_state.json exists and is newer than the local cache."""
    remote = remote_state_path(remote_root)
    if not remote.is_file():
        return False
    local = local_state_path(local_root)
    try:
        remote_mtime = remote.stat().st_mtime
    except OSError:
        return False
    if not local.is_file():
        return True
    try:
        local_mtime = local.stat().st_mtime
    except OSError:
        return True
    return remote_mtime > local_mtime


def save_json_to_remote_then_local(
    state: ProjectState,
    local_root: PathLike,
    remote_root: PathLike,
) -> None:
    """Write project_state.json to remote first, then local cache.

    If the remote write fails, the local cache is left unchanged and
    RemoteJsonError is raised. On success, any pending-remote marker is cleared.
    """
    remote = Path(remote_root)
    local = Path(local_root)
    remote_path = remote_state_path(remote)
    local_path = local_state_path(local)
    try:
        if not remote.is_dir():
            raise OSError(f"remote root is not a directory: {remote}")
        state.save_to_file(str(remote_path))
    except OSError as exc:
        raise RemoteJsonError(f"无法写入公盘 project_state.json: {exc}") from exc
    try:
        state.save_to_file(str(local_path))
    except OSError as exc:
        raise RemoteJsonError(
            f"公盘已写入，但本地缓存失败: {exc}"
        ) from exc
    clear_pending_remote_json(local)


def write_local_json_cache(state: ProjectState, local_root: PathLike) -> None:
    """Persist a local cache copy after a successful remote load."""
    state.save_to_file(str(local_state_path(local_root)))


def pending_remote_json_path(local_root: PathLike) -> Path:
    return Path(local_root) / PENDING_REMOTE_JSON_NAME


def is_pending_remote_json(local_root: PathLike) -> bool:
    return pending_remote_json_path(local_root).is_file()


def clear_pending_remote_json(local_root: PathLike) -> None:
    path = pending_remote_json_path(local_root)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _json_mtime(path: Path) -> Optional[float]:
    try:
        if path.is_file():
            return path.stat().st_mtime
    except OSError:
        return None
    return None


def pending_baseline_mtime(local_root: PathLike) -> Optional[float]:
    """mtime of the last-synced remote/local JSON, or None if not pending."""
    path = pending_remote_json_path(local_root)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return 0.0
        data = json.loads(raw)
        return float(data.get("baseline_mtime") or 0.0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0.0


def _pending_baseline_mtime(
    local_root: PathLike,
    remote_root: Optional[PathLike] = None,
) -> float:
    if remote_root is not None:
        remote_mtime = _json_mtime(remote_state_path(remote_root))
        if remote_mtime is not None:
            return remote_mtime
    local_mtime = _json_mtime(local_state_path(local_root))
    return local_mtime if local_mtime is not None else 0.0


def save_json_local_pending_remote(
    state: ProjectState,
    local_root: PathLike,
    remote_root: Optional[PathLike] = None,
    *,
    preserve_baseline: bool = False,
) -> None:
    """Write the local JSON cache and mark it pending upload to remote.

    ``baseline_mtime`` is the last-known remote (or local cache) mtime *before*
    this write, so reconnect can detect whether 公盘 changed in the meantime.
    Pass ``preserve_baseline=True`` to refresh the local file without treating
    the current remote mtime as a new sync point.
    """
    local = Path(local_root)
    if preserve_baseline and is_pending_remote_json(local):
        baseline = pending_baseline_mtime(local)
        if baseline is None:
            baseline = _pending_baseline_mtime(local, remote_root)
    else:
        baseline = _pending_baseline_mtime(local, remote_root)
    write_local_json_cache(state, local)
    pending_remote_json_path(local).write_text(
        json.dumps({"baseline_mtime": baseline}),
        encoding="utf-8",
    )


def remote_diverged_from_pending(
    local_root: PathLike,
    remote_root: PathLike,
) -> bool:
    """True when pending local JSON and remote JSON has moved past the baseline."""
    if not is_pending_remote_json(local_root):
        return False
    baseline = pending_baseline_mtime(local_root)
    if baseline is None:
        return False
    remote_mtime = _json_mtime(remote_state_path(remote_root))
    if remote_mtime is None:
        return False
    return remote_mtime > baseline


def is_purge_candidate(path: Path) -> bool:
    """True for nightly-purgeable local files (images, xlsx, or oversized)."""
    if path.suffix.lower() in _PURGE_EXTS:
        return True
    try:
        return path.stat().st_size > STRUCTURE_MIRROR_MAX_FILE_BYTES
    except OSError:
        return False


def _needs_upload(src: Path, dst: Path) -> bool:
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


def _sizes_match(local_file: Path, remote_file: Path) -> bool:
    try:
        return local_file.stat().st_size == remote_file.stat().st_size
    except OSError:
        return False


def incremental_upload(
    local_root: PathLike,
    remote_root: PathLike,
    cancelled: Optional[Callable[[], bool]] = None,
) -> SyncReport:
    """Copy new/changed local files to remote (incl. 备用/). Does not purge."""
    local = Path(local_root)
    remote = Path(remote_root)
    report = SyncReport()
    if not local.is_dir():
        report.failed.append(UploadFailure("", f"本地根不存在: {local}"))
        return report
    if not remote.is_dir():
        report.failed.append(UploadFailure("", f"公盘根不可用: {remote}"))
        return report

    for dirpath, dirnames, filenames in os.walk(local):
        if cancelled and cancelled():
            break
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIR_NAMES and d != THUMBS_DIR_NAME and not d.startswith(".")
        ]
        rel_dir = Path(dirpath).relative_to(local)
        for name in filenames:
            if cancelled and cancelled():
                break
            if should_skip_file(name) or name.startswith("."):
                continue
            src = Path(dirpath) / name
            if not src.is_file():
                continue
            rel = (rel_dir / name).as_posix()
            dest = remote / rel
            if not _needs_upload(src, dest):
                # Already in sync — still eligible for purge
                report.uploaded.append(rel)
                continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                report.uploaded.append(rel)
            except OSError as exc:
                report.failed.append(UploadFailure(rel, str(exc)))
    return report


def purge_verified_uploads(
    local_root: PathLike,
    remote_root: PathLike,
    relative_paths: Optional[Sequence[str]] = None,
) -> List[str]:
    """Delete local purge-candidates whose remote copy matches by size.

    Keeps directories and `.thumbs`. Returns purged relative paths.
    """
    local = Path(local_root)
    remote = Path(remote_root)
    purged: List[str] = []
    if relative_paths is None:
        return purged
    for rel in relative_paths:
        text = (rel or "").strip()
        if not text or ".." in Path(text).parts:
            continue
        local_file = local / text
        remote_file = remote / text
        if not local_file.is_file() or not remote_file.is_file():
            continue
        if not is_purge_candidate(local_file):
            continue
        if not _sizes_match(local_file, remote_file):
            continue
        try:
            local_file.unlink()
            purged.append(text)
        except OSError:
            continue
    return purged


def sync_project_to_remote(
    local_root: PathLike,
    remote_root: PathLike,
    cancelled: Optional[Callable[[], bool]] = None,
) -> SyncReport:
    """Upload then purge verified large/local media files."""
    report = incremental_upload(local_root, remote_root, cancelled=cancelled)
    if cancelled and cancelled():
        return report
    report.purged = purge_verified_uploads(local_root, remote_root, report.uploaded)
    return report
