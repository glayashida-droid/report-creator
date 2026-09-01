"""Resolve and probe network Excel sources configured in config.json."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from src.io.project_mirror import repo_root

_DATE_SUFFIX_RE = re.compile(r"-(\d{8})(?=\.[^.]+$)")

# Report export templates expected under report_templates/
REPORT_TEMPLATE_FILES = {
    "中文": "template_zh.docx",
    "英文": "template_en.docx",
    "中英文": "template_ze.docx",
}
REPORT_TEMPLATE_4SIGN_FILES = {
    "中文": "template_zh_4sign.docx",
    "英文": "template_en_4sign.docx",
    "中英文": "template_ze_4sign.docx",
}
REPORT_TEMPLATE_FALLBACK = "template_raw.docx"


@dataclass(frozen=True)
class EquipmentListSource:
    directory: str
    file_prefix: str
    extension: str = ".xlsx"


@dataclass(frozen=True)
class StandardsLibrarySource:
    file: str


@dataclass(frozen=True)
class DirectorySource:
    directory: str


@dataclass(frozen=True)
class ConnectionCheckConfig:
    retry_interval_disconnected_sec: int = 30
    retry_interval_connected_sec: int = 60


@dataclass(frozen=True)
class NetworkSourcesConfig:
    equipment_list: EquipmentListSource
    standards_library: StandardsLibrarySource
    leg_templates: DirectorySource
    report_templates: DirectorySource
    data_tables: DirectorySource
    connection_check: ConnectionCheckConfig


@dataclass(frozen=True)
class ProbeResult:
    equipment_ok: bool
    standards_ok: bool
    templates_ok: bool
    equipment_path: Optional[str]
    standards_path: Optional[str]
    equipment_error: str
    standards_error: str
    templates_error: str


def default_config_path() -> Path:
    return repo_root() / "config.json"


def _directory_source(raw: dict, key: str, default: str = "") -> DirectorySource:
    block = raw.get(key) or {}
    if isinstance(block, str):
        return DirectorySource(directory=block.strip())
    return DirectorySource(directory=str(block.get("directory") or default).strip())


def load_network_sources_config(path: Optional[Path] = None) -> NetworkSourcesConfig:
    cfg_path = path or default_config_path()
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    network = raw.get("network_sources") or {}
    equipment = network.get("equipment_list") or {}
    standards = network.get("standards_library") or {}
    check = raw.get("connection_check") or {}
    return NetworkSourcesConfig(
        equipment_list=EquipmentListSource(
            directory=str(equipment.get("directory") or "").strip(),
            file_prefix=str(equipment.get("file_prefix") or "01-设备清单").strip(),
            extension=str(equipment.get("extension") or ".xlsx").strip() or ".xlsx",
        ),
        standards_library=StandardsLibrarySource(
            file=str(standards.get("file") or "").strip(),
        ),
        leg_templates=_directory_source(network, "leg_templates"),
        report_templates=_directory_source(network, "report_templates"),
        data_tables=_directory_source(network, "data_tables"),
        connection_check=ConnectionCheckConfig(
            retry_interval_disconnected_sec=int(
                check.get("retry_interval_disconnected_sec") or 30
            ),
            retry_interval_connected_sec=int(
                check.get("retry_interval_connected_sec") or 60
            ),
        ),
    )


def _smb_url_to_unc(text: str) -> str:
    without_scheme = text[6:]
    parts = [p for p in without_scheme.split("/") if p]
    if not parts:
        return text
    host = parts[0]
    rest = parts[1:]
    if rest:
        return "\\\\" + host + "\\" + "\\".join(rest)
    return "\\\\" + host


def _unc_to_macos_volume_path(unc: str) -> str:
    """Map \\\\server\\share\\path to /Volumes/share/path when Finder has mounted it."""
    parts = [p for p in unc.replace("/", "\\").split("\\") if p]
    if len(parts) < 2:
        return unc
    share = parts[1]
    rest = parts[2:]
    volume = Path("/Volumes") / share
    return str(volume.joinpath(*rest)) if rest else str(volume)


_MOUNT_RETRY_COOLDOWN_SEC = 30.0
_last_mount_attempt_monotonic = 0.0


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _safe_glob(folder: Path, pattern: str) -> list[Path]:
    try:
        return [p for p in folder.glob(pattern) if _safe_is_file(p)]
    except OSError:
        return []


def _safe_stat_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _path_access_error(path: Path, label: str) -> str:
    try:
        path.exists()
    except OSError as exc:
        if getattr(exc, "errno", None) == 57:
            return f"{label}连接已断开，请在访达中重新连接公盘: {path}"
        return f"无法访问{label} {path}: {exc}"
    if not path.exists():
        return f"无法访问{label} {path}"
    return f"无法访问{label} {path}"


def _parse_smb_share_url(value: str) -> Optional[tuple[str, str]]:
    """Return (smb://host/share, share_name) for a configured smb/UNC path."""
    text = (value or "").strip()
    if text.startswith("smb://"):
        without_scheme = text[6:]
    elif text.startswith("\\\\"):
        without_scheme = text.lstrip("\\").replace("\\", "/")
    else:
        return None
    parts = [p for p in without_scheme.split("/") if p]
    if len(parts) < 2:
        return None
    host, share = parts[0], parts[1]
    return f"smb://{host}/{share}", share


def _collect_smb_shares(config: NetworkSourcesConfig) -> list[tuple[str, str]]:
    raw_paths: Iterable[str] = (
        config.equipment_list.directory,
        config.standards_library.file,
        config.leg_templates.directory,
        config.report_templates.directory,
        config.data_tables.directory,
    )
    shares: dict[str, str] = {}
    for raw in raw_paths:
        parsed = _parse_smb_share_url(raw)
        if parsed is None:
            continue
        mount_url, share_name = parsed
        shares[share_name] = mount_url
    return list(shares.items())


def _configured_path_usable(raw: str) -> bool:
    normalized = normalize_config_path(raw)
    if not normalized:
        return True
    path = Path(normalized)
    try:
        if _safe_is_file(path):
            with path.open("rb") as handle:
                handle.read(1)
            return True
        if _safe_is_dir(path):
            next(path.iterdir(), None)
            return True
    except OSError:
        return False
    return False


def _needs_smb_mount(config: NetworkSourcesConfig) -> bool:
    raw_paths: Iterable[str] = (
        config.equipment_list.directory,
        config.standards_library.file,
        config.leg_templates.directory,
        config.report_templates.directory,
        config.data_tables.directory,
    )
    for raw in raw_paths:
        if _parse_smb_share_url(raw) is None:
            continue
        if not _configured_path_usable(raw):
            return True
    return False


def attempt_mount_network_shares(config: NetworkSourcesConfig) -> None:
    """On macOS, ask Finder to mount configured SMB shares when they are missing or stale.

    Not used by background probes — those only check path readability so offline
    editing is not interrupted by Finder/SMB mount dialogs stealing focus.
    """
    if sys.platform != "darwin":
        return
    global _last_mount_attempt_monotonic
    now = time.monotonic()
    if now - _last_mount_attempt_monotonic < _MOUNT_RETRY_COOLDOWN_SEC:
        return
    shares = _collect_smb_shares(config)
    if not shares or not _needs_smb_mount(config):
        return
    _last_mount_attempt_monotonic = now
    for _share_name, mount_url in shares:
        subprocess.run(["open", mount_url], check=False)


def normalize_config_path(value: str) -> str:
    """Normalize config paths for the current OS.

    Config stores Windows UNC (\\\\server\\share\\...) or smb:// URLs. On macOS,
    SMB shares mounted via Finder appear under /Volumes/<share>/..., so we rewrite there.
    """
    text = (value or "").strip()
    if text.startswith("smb://"):
        text = _smb_url_to_unc(text)
    if sys.platform == "darwin" and text.startswith("\\\\"):
        return _unc_to_macos_volume_path(text)
    return text


def resolve_directory(source: DirectorySource) -> Optional[Path]:
    path_text = normalize_config_path(source.directory)
    if not path_text:
        return None
    path = Path(path_text)
    return path if _safe_is_dir(path) else None


def resolve_config_directory(configured: str) -> Path:
    """Return normalized Path for a configured directory (may not exist yet)."""
    return Path(normalize_config_path(configured))


def leg_templates_directory(config: Optional[NetworkSourcesConfig] = None) -> Path:
    cfg = config or load_network_sources_config()
    return resolve_config_directory(cfg.leg_templates.directory)


def report_templates_directory(config: Optional[NetworkSourcesConfig] = None) -> Path:
    cfg = config or load_network_sources_config()
    return resolve_config_directory(cfg.report_templates.directory)


def data_table_templates_directory(config: Optional[NetworkSourcesConfig] = None) -> Path:
    cfg = config or load_network_sources_config()
    return resolve_config_directory(cfg.data_tables.directory)


def resolve_report_template_file(
    filename: str, config: Optional[NetworkSourcesConfig] = None
) -> Optional[Path]:
    folder = report_templates_directory(config)
    path = folder / filename
    return path if _safe_is_file(path) else None


def resolve_report_template_for_language(
    lang: str,
    config: Optional[NetworkSourcesConfig] = None,
    *,
    use_4sign: bool = False,
) -> Optional[Path]:
    mapping = REPORT_TEMPLATE_4SIGN_FILES if use_4sign else REPORT_TEMPLATE_FILES
    filename = mapping.get(lang, mapping["中文"])
    path = resolve_report_template_file(filename, config)
    if path is not None:
        return path
    if use_4sign:
        return resolve_report_template_for_language(lang, config, use_4sign=False)
    if lang == "中文":
        return resolve_report_template_file(REPORT_TEMPLATE_FALLBACK, config)
    return None


def _date_from_filename(name: str, prefix: str) -> Optional[int]:
    if not name.startswith(prefix):
        return None
    match = _DATE_SUFFIX_RE.search(name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def resolve_equipment_list_file(source: EquipmentListSource) -> Optional[Path]:
    directory = normalize_config_path(source.directory)
    if not directory:
        return None
    folder = Path(directory)
    if not _safe_is_dir(folder):
        return None
    ext = source.extension if source.extension.startswith(".") else f".{source.extension}"
    pattern = f"{source.file_prefix}*{ext}"
    matches = _safe_glob(folder, pattern)
    if not matches:
        return None

    def sort_key(path: Path) -> tuple:
        dated = _date_from_filename(path.name, source.file_prefix)
        if dated is not None:
            return (1, dated, _safe_stat_mtime(path))
        return (0, 0, _safe_stat_mtime(path))

    return max(matches, key=sort_key)


def resolve_standards_library_file(source: StandardsLibrarySource) -> Optional[Path]:
    path_text = normalize_config_path(source.file)
    if not path_text:
        return None
    path = Path(path_text)
    return path if _safe_is_file(path) else None


def probe_readable_file(path: Optional[Path]) -> Tuple[bool, str]:
    if path is None:
        return False, "未找到文件"
    try:
        exists = path.exists()
    except OSError as exc:
        if getattr(exc, "errno", None) == 57:
            return False, f"公盘连接已断开，请在访达中重新连接: {path}"
        return False, f"无法访问 {path}: {exc}"
    if not exists:
        return False, f"无法访问 {path}"
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        return False, f"无法打开 {path}: {exc}"
    return True, ""


def probe_accessible_directory(path: Optional[Path], label: str) -> Tuple[bool, str]:
    if path is None:
        return False, f"{label}目录未找到"
    if not _safe_is_dir(path):
        return False, _path_access_error(path, label)
    try:
        next(path.iterdir(), None)
    except OSError as exc:
        return False, f"无法读取{label} {path}: {exc}"
    return True, ""


def probe_template_sources(config: NetworkSourcesConfig) -> Tuple[bool, str]:
    errors: list[str] = []

    leg_dir = resolve_directory(config.leg_templates)
    ok, err = probe_accessible_directory(leg_dir, "Leg模板")
    if not ok:
        errors.append(err)

    report_dir = resolve_directory(config.report_templates)
    ok, err = probe_accessible_directory(report_dir, "报告模板")
    if not ok:
        errors.append(err)
    elif report_dir is not None:
        for filename in REPORT_TEMPLATE_FILES.values():
            if not _safe_is_file(report_dir / filename):
                errors.append(f"报告模板缺少 {filename}")

    data_dir = resolve_directory(config.data_tables)
    ok, err = probe_accessible_directory(data_dir, "数据表模板")
    if not ok:
        errors.append(err)

    if errors:
        return False, "; ".join(errors)
    return True, ""


def probe_network_sources(config: Optional[NetworkSourcesConfig] = None) -> ProbeResult:
    """Probe configured paths for readability only — no Finder/SMB open (avoids focus steal)."""
    cfg = config or load_network_sources_config()
    equipment_path = resolve_equipment_list_file(cfg.equipment_list)
    standards_path = resolve_standards_library_file(cfg.standards_library)
    equipment_ok, equipment_error = probe_readable_file(equipment_path)
    standards_ok, standards_error = probe_readable_file(standards_path)
    templates_ok, templates_error = probe_template_sources(cfg)
    if equipment_path is None and not equipment_error:
        equipment_error = f"目录中未找到 {cfg.equipment_list.file_prefix}*.xlsx"
    if standards_path is None and not standards_error:
        standards_error = f"无法访问 {cfg.standards_library.file}"
    return ProbeResult(
        equipment_ok=equipment_ok,
        standards_ok=standards_ok,
        templates_ok=templates_ok,
        equipment_path=str(equipment_path) if equipment_path else None,
        standards_path=str(standards_path) if standards_path else None,
        equipment_error=equipment_error,
        standards_error=standards_error,
        templates_error=templates_error,
    )
