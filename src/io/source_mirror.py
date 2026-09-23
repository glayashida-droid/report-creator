"""Copy公盘 templates, the standards workbook, and the equipment list into templates/.

Reads use those local files. A later launch compares file name (equipment list),
size, and mtime against the share and copies again only when one of those changed.
The equipment list is re-picked by dated filename; the previous file is never
treated as current just because its own bytes stayed the same.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.io.network_sources import (
    ELP_TEMPLATE_FILENAMES,
    REPORT_TEMPLATE_4SIGN_FILES,
    REPORT_TEMPLATE_FALLBACK,
    REPORT_TEMPLATE_FILES,
    NetworkSourcesConfig,
    StandardsLibrarySource,
    _pick_equipment_file,
    local_fallback_for,
    normalize_config_path,
    resolve_elp_report_template,
    resolve_report_template_for_language,
)

_MANIFEST_NAME = ".source_mirror.json"
_DIR_KINDS = (
    "leg_templates",
    "report_templates",
    "data_tables",
    "original_data_sheet",
    "elp_data_patten",
)
_SKIP_NAMES = {"Thumbs.db", "desktop.ini"}


@dataclass
class SourceMirrorResult:
    standards_changed: bool = False
    equipment_changed: bool = False
    templates_changed: bool = False
    error: str = ""
    errors: list[str] = field(default_factory=list)


def manifest_path() -> Path:
    from src.io.network_sources import local_fallback_root as current_root

    return current_root() / _MANIFEST_NAME


def prefer_local_tree(kind: str, fallback: Callable[[], Path]) -> Path:
    """Use the mirrored templates folder when it exists."""
    local = local_fallback_for(kind)
    try:
        if local.is_dir():
            return local
    except OSError:
        pass
    return fallback()


def local_standards_file() -> Optional[Path]:
    path = local_fallback_for("standards_library")
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def local_equipment_file(config: NetworkSourcesConfig) -> Optional[Path]:
    """Current equipment workbook: manifest winner, else the newest dated local file."""
    folder = local_fallback_for("equipment_list")
    recorded = _load_manifest().get("equipment") or {}
    name = str(recorded.get("name") or "")
    if name and not _skip_name(name):
        path = folder / name
        try:
            if path.is_file():
                return path
        except OSError:
            pass
    return _pick_equipment_file(folder, config.equipment_list)


def mirror_saved_file(kind: str, src: Path) -> None:
    """Keep a file just written to the share in the local mirror as well."""
    dest_dir = local_fallback_for(kind)
    dest = dest_dir / src.name
    try:
        if src.resolve() == dest.resolve():
            return
    except OSError:
        return
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    except OSError:
        return


def read_report_template_for_language(
    lang: str,
    config: Optional[NetworkSourcesConfig] = None,
    *,
    use_4sign: bool = False,
) -> Optional[Path]:
    folder = local_fallback_for("report_templates")
    mapping = REPORT_TEMPLATE_4SIGN_FILES if use_4sign else REPORT_TEMPLATE_FILES
    filename = mapping.get(lang, mapping["中文"])
    path = folder / filename
    try:
        if path.is_file():
            return path
    except OSError:
        pass
    if use_4sign:
        plain = read_report_template_for_language(lang, config, use_4sign=False)
        if plain is not None:
            return plain
    elif lang == "中文":
        fallback = folder / REPORT_TEMPLATE_FALLBACK
        try:
            if fallback.is_file():
                return fallback
        except OSError:
            pass
    return resolve_report_template_for_language(lang, config, use_4sign=use_4sign)


def read_elp_report_template(
    config: Optional[NetworkSourcesConfig] = None,
) -> Optional[Path]:
    folder = local_fallback_for("report_templates")
    for name in ELP_TEMPLATE_FILENAMES:
        path = folder / name
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    try:
        matches = sorted(
            p
            for p in folder.glob("*ELP*.docx")
            if p.is_file() and not p.name.startswith("~")
        )
    except OSError:
        matches = []
    if matches:
        return matches[0]
    return resolve_elp_report_template(config)


def sync_source_mirror(
    config: NetworkSourcesConfig, cancelled=None
) -> SourceMirrorResult:
    """Stat the share once and copy files whose name, size, or mtime changed."""
    result = SourceMirrorResult()
    manifest = _load_manifest()
    try:
        if not _stop_requested(cancelled):
            _sync_standards(config, manifest, result)
        if not _stop_requested(cancelled):
            _sync_equipment(config, manifest, result)
        if not _stop_requested(cancelled):
            _sync_directories(config, manifest, result, cancelled=cancelled)
    except Exception as exc:
        result.error = str(exc)
        result.errors.append(str(exc))
    _save_manifest(manifest)
    return result


def _stop_requested(cancelled) -> bool:
    return bool(cancelled is not None and cancelled())


def _sync_standards(
    config: NetworkSourcesConfig, manifest: dict, result: SourceMirrorResult
) -> None:
    remote = _configured_file(config.standards_library)
    if remote is None:
        return
    stamp = _stamp(remote)
    if stamp is None:
        return
    dest = local_fallback_for("standards_library")
    recorded = manifest.get("standards") if isinstance(manifest.get("standards"), dict) else None
    if not _needs_copy(dest, stamp, recorded):
        manifest["standards"] = stamp
        return
    try:
        _copy_file(remote, dest)
    except OSError as exc:
        result.errors.append(f"标准库: {exc}")
        return
    manifest["standards"] = stamp
    result.standards_changed = True


def _sync_equipment(
    config: NetworkSourcesConfig, manifest: dict, result: SourceMirrorResult
) -> None:
    folder = _configured_dir(config.equipment_list.directory)
    if folder is None:
        return
    picked = _pick_equipment_file(folder, config.equipment_list)
    if picked is None:
        return
    stamp = _stamp(picked)
    if stamp is None:
        return
    record = {"name": picked.name, **stamp}
    dest = local_fallback_for("equipment_list") / picked.name
    recorded = manifest.get("equipment") if isinstance(manifest.get("equipment"), dict) else None
    same_file = isinstance(recorded, dict) and recorded.get("name") == picked.name
    if same_file and not _needs_copy(dest, stamp, recorded):
        manifest["equipment"] = record
        return
    try:
        _copy_file(picked, dest)
    except OSError as exc:
        result.errors.append(f"设备清单: {exc}")
        return
    manifest["equipment"] = record
    result.equipment_changed = True


def _sync_directories(
    config: NetworkSourcesConfig,
    manifest: dict,
    result: SourceMirrorResult,
    cancelled=None,
) -> None:
    dirs = manifest.get("dirs")
    if not isinstance(dirs, dict):
        dirs = {}
        manifest["dirs"] = dirs
    sources = {
        "leg_templates": config.leg_templates,
        "report_templates": config.report_templates,
        "data_tables": config.data_tables,
        "original_data_sheet": config.original_data_sheet,
        "elp_data_patten": config.elp_data_patten,
    }
    for kind in _DIR_KINDS:
        if _stop_requested(cancelled):
            return
        source = sources[kind]
        remote_root = _configured_dir(source.directory)
        if remote_root is None:
            continue
        found = _list_tree(remote_root)
        if found is None:
            continue
        previous = dirs.get(kind) if isinstance(dirs.get(kind), dict) else {}
        new_map, changed, errors = _sync_tree(
            local_fallback_for(kind), found, previous, cancelled=cancelled
        )
        dirs[kind] = new_map
        result.errors.extend(errors)
        if changed:
            result.templates_changed = True


def _sync_tree(
    local_root: Path, found: dict[str, Path], previous: dict, cancelled=None
) -> tuple[dict, bool, list[str]]:
    new_map: dict = {}
    changed = False
    errors: list[str] = []
    for rel, path in found.items():
        if _stop_requested(cancelled):
            return new_map, changed, errors
        stamp = _stamp(path)
        recorded = previous.get(rel) if isinstance(previous.get(rel), dict) else None
        if stamp is None:
            if recorded is not None:
                new_map[rel] = recorded
            continue
        dest = local_root / rel
        if _needs_copy(dest, stamp, recorded):
            try:
                _copy_file(path, dest)
            except OSError as exc:
                errors.append(f"{rel}: {exc}")
                if recorded is not None:
                    new_map[rel] = recorded
                continue
            changed = True
        new_map[rel] = stamp
    for rel, recorded in previous.items():
        if _stop_requested(cancelled):
            return new_map, changed, errors
        if rel in found or rel in new_map:
            continue
        dest = local_root / rel
        try:
            if dest.is_file():
                dest.unlink()
                changed = True
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
            if isinstance(recorded, dict):
                new_map[rel] = recorded
    return new_map, changed, errors


def _configured_file(source: StandardsLibrarySource) -> Optional[Path]:
    text = normalize_config_path(source.file)
    if not text:
        return None
    path = Path(text)
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _configured_dir(directory: str) -> Optional[Path]:
    text = normalize_config_path(directory)
    if not text:
        return None
    path = Path(text)
    try:
        return path if path.is_dir() else None
    except OSError:
        return None


def _list_tree(root: Path) -> Optional[dict[str, Path]]:
    try:
        if not root.is_dir():
            return None
    except OSError:
        return None
    found: dict[str, Path] = {}
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
            for name in filenames:
                if _skip_name(name):
                    continue
                path = Path(dirpath) / name
                found[path.relative_to(root).as_posix()] = path
    except OSError:
        return None
    return found


def _skip_name(name: str) -> bool:
    return name.startswith(".") or name.startswith("~$") or name in _SKIP_NAMES


def _stamp(path: Path) -> Optional[dict]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _needs_copy(dest: Path, stamp: dict, recorded: Optional[dict]) -> bool:
    if not isinstance(recorded, dict):
        return True
    if recorded.get("size") != stamp["size"] or recorded.get("mtime_ns") != stamp["mtime_ns"]:
        return True
    try:
        return dest.stat().st_size != stamp["size"]
    except OSError:
        return True


def _copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.mirror-tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _load_manifest() -> dict:
    path = manifest_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(manifest: dict) -> None:
    path = manifest_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return
