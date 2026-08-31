from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.io.network_sources import (
    EquipmentListSource,
    _safe_is_dir,
    attempt_mount_network_shares,
    load_network_sources_config,
    normalize_config_path,
    probe_network_sources,
    probe_template_sources,
    resolve_equipment_list_file,
    resolve_report_template_for_language,
)
from src.parsers.db_loader import BaseDataLoader


def test_normalize_smb_to_unc_on_windows():
    raw = "smb://10.10.31.8/材料实验室a/01-E&E/D01 设备信息"
    with patch("src.io.network_sources.sys.platform", "win32"):
        assert normalize_config_path(raw) == "\\\\10.10.31.8\\材料实验室a\\01-E&E\\D01 设备信息"


def test_normalize_unc_to_macos_volume():
    raw = "\\\\10.10.31.8\\材料实验室a\\01-E&E\\D01 设备信息"
    with patch("src.io.network_sources.sys.platform", "darwin"):
        assert normalize_config_path(raw) == "/Volumes/材料实验室a/01-E&E/D01 设备信息"


def test_normalize_smb_standard_sheet_path_on_macos():
    raw = (
        "smb://10.10.31.8/材料实验室b/车载电子/report_creator/standard sheet/标准库.xlsx"
    )
    with patch("src.io.network_sources.sys.platform", "darwin"):
        assert normalize_config_path(raw) == (
            "/Volumes/材料实验室b/车载电子/report_creator/standard sheet/标准库.xlsx"
        )


def test_resolve_equipment_list_prefers_latest_date(tmp_path: Path):
    folder = tmp_path / "equipment"
    folder.mkdir()
    older = folder / "01-设备清单-20260101.xlsx"
    newer = folder / "01-设备清单-20260825.xlsx"
    older.write_bytes(b"a")
    newer.write_bytes(b"b")
    source = EquipmentListSource(
        directory=str(folder),
        file_prefix="01-设备清单",
        extension=".xlsx",
    )
    assert resolve_equipment_list_file(source) == newer


def test_resolve_equipment_list_falls_back_to_mtime(tmp_path: Path):
    folder = tmp_path / "equipment"
    folder.mkdir()
    plain = folder / "01-设备清单.xlsx"
    plain.write_bytes(b"a")
    source = EquipmentListSource(
        directory=str(folder),
        file_prefix="01-设备清单",
        extension=".xlsx",
    )
    assert resolve_equipment_list_file(source) == plain


def test_resolve_equipment_list_handles_stale_mount():
    source = EquipmentListSource(
        directory="/Volumes/材料实验室a/01-E&E/D01 设备信息",
        file_prefix="01-设备清单",
        extension=".xlsx",
    )
    with patch.object(Path, "is_dir", side_effect=OSError(57, "Socket is not connected")):
        assert resolve_equipment_list_file(source) is None


def test_safe_is_dir_handles_oserror():
    path = Path("/Volumes/missing-share")
    with patch.object(Path, "is_dir", side_effect=OSError(57, "Socket is not connected")):
        assert _safe_is_dir(path) is False


def test_attempt_mount_network_shares_opens_missing_volumes(tmp_path: Path):
    cfg_path = _write_config(
        tmp_path,
        network_sources={
            "equipment_list": {
                "directory": "smb://10.10.31.8/材料实验室a/01-E&E/D01 设备信息",
                "file_prefix": "01-设备清单",
                "extension": ".xlsx",
            },
            "standards_library": {
                "file": "smb://10.10.31.8/材料实验室b/车载电子/report_creator/standard sheet/标准库.xlsx"
            },
            "leg_templates": {
                "directory": "smb://10.10.31.8/材料实验室b/车载电子/report_creator/leg_templates"
            },
            "report_templates": {
                "directory": "smb://10.10.31.8/材料实验室b/车载电子/report_creator/report_templates"
            },
            "data_tables": {
                "directory": "smb://10.10.31.8/材料实验室b/车载电子/report_creator/data_tables"
            },
        },
    )
    config = load_network_sources_config(cfg_path)
    with patch("src.io.network_sources.sys.platform", "darwin"), patch(
        "src.io.network_sources._needs_smb_mount", return_value=True
    ), patch("src.io.network_sources.subprocess.run") as run_mock, patch(
        "src.io.network_sources.time.monotonic", return_value=1000.0
    ), patch("src.io.network_sources._last_mount_attempt_monotonic", 0.0):
        attempt_mount_network_shares(config)
        opened = [call.args[0][1] for call in run_mock.call_args_list]
        assert "smb://10.10.31.8/材料实验室a" in opened
        assert "smb://10.10.31.8/材料实验室b" in opened


def _write_config(tmp_path: Path, **overrides) -> Path:
    leg = tmp_path / "leg_templates"
    report = tmp_path / "report_templates"
    data = tmp_path / "data_tables"
    leg.mkdir()
    report.mkdir()
    data.mkdir()
    for name in ("template_zh.docx", "template_en.docx", "template_ze.docx"):
        (report / name).write_bytes(b"t")
    equipment_dir = tmp_path / "equipment"
    equipment_dir.mkdir()
    equipment_file = equipment_dir / "01-设备清单-20260825.xlsx"
    equipment_file.write_bytes(b"x")
    standards_file = tmp_path / "标准库.xlsx"
    standards_file.write_bytes(b"y")

    payload = {
        "network_sources": {
            "equipment_list": {
                "directory": str(equipment_dir),
                "file_prefix": "01-设备清单",
                "extension": ".xlsx",
            },
            "standards_library": {"file": str(standards_file)},
            "leg_templates": {"directory": str(leg)},
            "report_templates": {"directory": str(report)},
            "data_tables": {"directory": str(data)},
        },
        "connection_check": {
            "retry_interval_disconnected_sec": 30,
            "retry_interval_connected_sec": 60,
        },
    }
    payload["network_sources"].update(overrides.get("network_sources") or {})
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(payload), encoding="utf-8")
    return cfg_path


def test_probe_network_sources_with_local_files(tmp_path: Path):
    cfg_path = _write_config(tmp_path)
    config = load_network_sources_config(cfg_path)
    result = probe_network_sources(config)
    assert result.equipment_ok is True
    assert result.standards_ok is True
    assert result.templates_ok is True
    assert result.equipment_path.endswith("01-设备清单-20260825.xlsx")
    assert result.standards_path.endswith("标准库.xlsx")


def test_probe_templates_fails_when_report_template_missing(tmp_path: Path):
    cfg_path = _write_config(tmp_path)
    config = load_network_sources_config(cfg_path)
    (Path(config.report_templates.directory) / "template_en.docx").unlink()
    ok, err = probe_template_sources(config)
    assert ok is False
    assert "template_en.docx" in err


def test_resolve_report_template_for_language(tmp_path: Path):
    cfg_path = _write_config(tmp_path)
    config = load_network_sources_config(cfg_path)
    zh = resolve_report_template_for_language("中文", config)
    assert zh is not None
    assert zh.name == "template_zh.docx"


def test_db_loader_network_mode_requires_probe(tmp_path: Path):
    standards = tmp_path / "标准库.xlsx"
    equipment = tmp_path / "01-设备清单.xlsx"
    standards.write_bytes(b"x")
    equipment.write_bytes(b"y")

    loader = BaseDataLoader(network_mode=True)
    assert loader.is_standards_ready is False
    assert loader.is_equipment_ready is False

    loader.apply_network_probe(
        standards_path=str(standards),
        standards_ok=True,
        equipment_path=str(equipment),
        equipment_ok=True,
    )
    assert loader.is_standards_ready is True
    assert loader.is_equipment_ready is True


def test_db_loader_network_mode_clears_equipment_cache_on_path_change(tmp_path: Path):
    first = tmp_path / "01-设备清单-20260101.xlsx"
    second = tmp_path / "01-设备清单-20260825.xlsx"
    standards = tmp_path / "标准库.xlsx"
    first.write_bytes(b"old")
    second.write_bytes(b"new")
    standards.write_bytes(b"std")

    loader = BaseDataLoader(network_mode=True)
    loader.apply_network_probe(
        standards_path=str(standards),
        standards_ok=True,
        equipment_path=str(first),
        equipment_ok=True,
    )
    loader.apply_network_probe(
        standards_path=str(standards),
        standards_ok=True,
        equipment_path=str(second),
        equipment_ok=True,
    )
    assert loader._equipment_path == str(second)
    assert loader.equipments_df is None
