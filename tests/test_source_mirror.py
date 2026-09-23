"""Local mirror of公盘 templates: name/size/mtime, with dated equipment files."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.io.network_sources import (
    ConnectionCheckConfig,
    DirectorySource,
    EquipmentListSource,
    NetworkSourcesConfig,
    StandardsLibrarySource,
)
from src.io.source_mirror import (
    local_equipment_file,
    sync_source_mirror,
)
from src.parsers.db_loader import BaseDataLoader


def _config(
    *,
    equipment: str = "",
    standards: str = "",
    folders: dict | None = None,
) -> NetworkSourcesConfig:
    folders = folders or {}
    return NetworkSourcesConfig(
        equipment_list=EquipmentListSource(
            directory=equipment,
            file_prefix="01-设备清单",
            extension=".xlsx",
        ),
        standards_library=StandardsLibrarySource(file=standards),
        leg_templates=DirectorySource(directory=folders.get("leg_templates", "")),
        report_templates=DirectorySource(directory=folders.get("report_templates", "")),
        data_tables=DirectorySource(directory=folders.get("data_tables", "")),
        original_data_sheet=DirectorySource(directory=folders.get("original_data_sheet", "")),
        elp_data_patten=DirectorySource(directory=folders.get("elp_data_patten", "")),
        connection_check=ConnectionCheckConfig(),
    )


@pytest.fixture
def mirrored(tmp_path, monkeypatch):
    root = tmp_path / "templates"
    root.mkdir()
    monkeypatch.setattr("src.io.network_sources.local_fallback_root", lambda: root)
    return root


def test_equipment_picks_new_dated_file_even_if_old_file_is_untouched(mirrored):
    remote = mirrored.parent / "eq"
    remote.mkdir()
    old = remote / "01-设备清单-20260101.xlsx"
    newer = remote / "01-设备清单-20260923.xlsx"
    old.write_bytes(b"old-file")
    newer.write_bytes(b"new-file")
    os.utime(old, (9_000_000_000, 9_000_000_000))
    local_old = mirrored / old.name
    local_old.write_bytes(b"old-file")
    os.utime(local_old, (old.stat().st_atime, old.stat().st_mtime))
    manifest = {
        "equipment": {
            "name": old.name,
            "size": old.stat().st_size,
            "mtime_ns": old.stat().st_mtime_ns,
        }
    }
    (mirrored / ".source_mirror.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = sync_source_mirror(_config(equipment=str(remote)))

    assert result.equipment_changed is True
    assert (mirrored / newer.name).read_bytes() == b"new-file"
    assert local_equipment_file(_config(equipment=str(remote))) == mirrored / newer.name
    saved = json.loads((mirrored / ".source_mirror.json").read_text(encoding="utf-8"))
    assert saved["equipment"]["name"] == newer.name


def test_unchanged_equipment_is_not_copied_again(mirrored, monkeypatch):
    remote = mirrored.parent / "eq"
    remote.mkdir()
    current = remote / "01-设备清单-20260923.xlsx"
    current.write_bytes(b"same")
    sync_source_mirror(_config(equipment=str(remote)))

    def fail_copy(*_args, **_kwargs):
        raise AssertionError("unchanged equipment was copied")

    monkeypatch.setattr("src.io.source_mirror._copy_file", fail_copy)
    again = sync_source_mirror(_config(equipment=str(remote)))
    assert again.equipment_changed is False


def test_local_equipment_file_ignores_a_newer_stray_name(mirrored):
    winner = mirrored / "01-设备清单-20260825.xlsx"
    stray = mirrored / "01-设备清单-20261201.xlsx"
    winner.write_bytes(b"win")
    stray.write_bytes(b"stray")
    (mirrored / ".source_mirror.json").write_text(
        json.dumps({"equipment": {"name": winner.name, "size": 3, "mtime_ns": 1}}),
        encoding="utf-8",
    )
    assert local_equipment_file(_config()) == winner


def test_standards_copy_follows_size_and_mtime(mirrored):
    remote = mirrored.parent / "标准库.xlsx"
    remote.write_bytes(b"v1")
    first = sync_source_mirror(_config(standards=str(remote)))
    assert first.standards_changed is True
    dest = mirrored / "standard sheet" / "标准库.xlsx"
    assert dest.read_bytes() == b"v1"

    second = sync_source_mirror(_config(standards=str(remote)))
    assert second.standards_changed is False

    remote.write_bytes(b"v2-changed")
    third = sync_source_mirror(_config(standards=str(remote)))
    assert third.standards_changed is True
    assert dest.read_bytes() == b"v2-changed"


def test_directory_mirror_skips_lockfiles_and_keeps_local_extras(mirrored):
    remote = mirrored.parent / "data_tables"
    nested = remote / "子目录"
    nested.mkdir(parents=True)
    (nested / "五点.xlsx").write_bytes(b"sheet")
    (remote / "~$五点.xlsx").write_bytes(b"lock")
    local = mirrored / "data_tables"
    local.mkdir()
    (local / "README.md").write_text("keep", encoding="utf-8")
    gone = local / "removed.xlsx"
    gone.write_bytes(b"bye")
    (mirrored / ".source_mirror.json").write_text(
        json.dumps(
            {
                "dirs": {
                    "data_tables": {
                        "removed.xlsx": {"size": 3, "mtime_ns": 1},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = sync_source_mirror(_config(folders={"data_tables": str(remote)}))

    assert result.templates_changed is True
    assert (local / "子目录" / "五点.xlsx").read_bytes() == b"sheet"
    assert not (local / "~$五点.xlsx").exists()
    assert (local / "README.md").read_text(encoding="utf-8") == "keep"
    assert not gone.exists()


def test_unreachable_share_leaves_the_local_file(mirrored):
    dest = mirrored / "standard sheet"
    dest.mkdir()
    book = dest / "标准库.xlsx"
    book.write_bytes(b"stay")
    sync_source_mirror(_config(standards=str(mirrored.parent / "missing.xlsx")))
    assert book.read_bytes() == b"stay"


def test_forget_cached_catalog_drops_only_the_requested_side(tmp_path):
    standards = tmp_path / "标准库.xlsx"
    equipment = tmp_path / "01-设备清单.xlsx"
    standards.write_bytes(b"s")
    equipment.write_bytes(b"e")
    loader = BaseDataLoader(network_mode=True)
    loader.apply_network_probe(
        standards_path=str(standards),
        standards_ok=True,
        equipment_path=str(equipment),
        equipment_ok=True,
    )
    loader.standards_df = object()
    loader.equipments_df = object()
    loader.forget_cached_catalog(equipment=True)
    assert loader.standards_df is not None
    assert loader.equipments_df is None
