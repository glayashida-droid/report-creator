"""Project sync helpers — JSON remote lifecycle (photos/nightly land in later tickets)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from src.models.project_state import ProjectState

PathLike = Union[str, Path]
PROJECT_STATE_NAME = "project_state.json"


class RemoteJsonError(OSError):
    """Raised when project_state.json cannot be written to the remote root."""


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
    RemoteJsonError is raised so callers can keep dirty state.
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


def write_local_json_cache(state: ProjectState, local_root: PathLike) -> None:
    """Persist a local cache copy after a successful remote load."""
    state.save_to_file(str(local_state_path(local_root)))
