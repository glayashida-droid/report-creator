"""Resolve and probe network Excel sources configured in config.json."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.io.project_mirror import repo_root

_DATE_SUFFIX_RE = re.compile(r"-(\d{8})(?=\.[^.]+$)")

# Report export templates expected under report_templates/
REPORT_TEMPLATE_FILES = {
    "中文": "template_zh.docx",
    "英文": "template_en.docx",
    "中英文": "template_ze.docx",
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
    return path if path.is_dir() else None


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
    return path if path.is_file() else None


def resolve_report_template_for_language(
    lang: str, config: Optional[NetworkSourcesConfig] = None
) -> Optional[Path]:
    filename = REPORT_TEMPLATE_FILES.get(lang, REPORT_TEMPLATE_FILES["中文"])
    path = resolve_report_template_file(filename, config)
    if path is not None:
        return path
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
    if not folder.is_dir():
        return None
    ext = source.extension if source.extension.startswith(".") else f".{source.extension}"
    pattern = f"{source.file_prefix}*{ext}"
    matches = [p for p in folder.glob(pattern) if p.is_file()]
    if not matches:
        return None

    def sort_key(path: Path) -> tuple:
        dated = _date_from_filename(path.name, source.file_prefix)
        if dated is not None:
            return (1, dated, path.stat().st_mtime)
        return (0, 0, path.stat().st_mtime)

    return max(matches, key=sort_key)


def resolve_standards_library_file(source: StandardsLibrarySource) -> Optional[Path]:
    path_text = normalize_config_path(source.file)
    if not path_text:
        return None
    path = Path(path_text)
    return path if path.is_file() else None


def probe_readable_file(path: Optional[Path]) -> Tuple[bool, str]:
    if path is None:
        return False, "未找到文件"
    if not path.exists():
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
    if not path.is_dir():
        return False, f"无法访问{label} {path}"
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
            if not (report_dir / filename).is_file():
                errors.append(f"报告模板缺少 {filename}")

    data_dir = resolve_directory(config.data_tables)
    ok, err = probe_accessible_directory(data_dir, "数据表模板")
    if not ok:
        errors.append(err)

    if errors:
        return False, "; ".join(errors)
    return True, ""


def probe_network_sources(config: Optional[NetworkSourcesConfig] = None) -> ProbeResult:
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
