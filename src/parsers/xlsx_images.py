"""Extract in-cell and floating images from an .xlsx, keyed by Excel row number."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Dict, List
from xml.etree import ElementTree as ET

_IMAGE_MAGIC = (
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"GIF8",
    b"BM",
    b"RIFF",
)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _looks_like_image(data: bytes) -> bool:
    if not data or len(data) < 8:
        return False
    return any(data.startswith(magic) for magic in _IMAGE_MAGIC)


def _cell_row(ref: str) -> int | None:
    digits = "".join(ch for ch in (ref or "") if ch.isdigit())
    return int(digits) if digits else None


def _norm_zip_path(name: str) -> str:
    parts: List[str] = []
    for part in name.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(zf.read(name))
    except KeyError:
        return None


def _attr(el: ET.Element, *names: str) -> str:
    want = {n.lower() for n in names}
    for key, val in el.attrib.items():
        if _local(key).lower() in want:
            return val
    return ""


def _media_bytes(zf: zipfile.ZipFile, target: str, base: str) -> bytes | None:
    if not target:
        return None
    if target.startswith("/"):
        name = target.lstrip("/")
    else:
        name = _norm_zip_path(str(Path(base).parent / target))
    try:
        data = zf.read(name)
    except KeyError:
        return None
    return data if _looks_like_image(data) else None


def _rel_targets(zf: zipfile.ZipFile, rels_path: str) -> Dict[str, str]:
    root = _read_xml(zf, rels_path)
    if root is None:
        return {}
    out = {}
    for child in root:
        if _local(child.tag) != "Relationship":
            continue
        rid = _attr(child, "Id")
        target = _attr(child, "Target")
        if rid and target:
            out[rid] = target
    return out


def _rich_value_images(zf: zipfile.ZipFile) -> List[bytes]:
    """Image bytes for each rich-value row; index matches rdrichvalue order."""
    rel_root = _read_xml(zf, "xl/richData/richValueRel.xml")
    rels = _rel_targets(zf, "xl/richData/_rels/richValueRel.xml.rels")
    if rel_root is None or not rels:
        return []
    ordered_rids = [
        _attr(child, "id")
        for child in rel_root
        if _local(child.tag) == "rel" and _attr(child, "id")
    ]

    rv_root = _read_xml(zf, "xl/richData/rdrichvalue.xml")
    if rv_root is None:
        return []
    images: List[bytes] = []
    for rv in rv_root:
        if _local(rv.tag) != "rv":
            continue
        values = [c.text for c in rv if _local(c.tag) == "v"]
        data = b""
        if values:
            try:
                ident = int(values[0])
            except (TypeError, ValueError):
                ident = -1
            rid = ordered_rids[ident] if 0 <= ident < len(ordered_rids) else ""
            data = _media_bytes(zf, rels.get(rid, ""), "xl/richData/richValueRel.xml") or b""
        images.append(data)
    return images


def _vm_to_rich_index(zf: zipfile.ZipFile) -> Dict[int, int]:
    """Map 1-based cell vm value -> rdrichvalue index."""
    meta = _read_xml(zf, "xl/metadata.xml")
    if meta is None:
        return {}
    future_indices: List[int] = []
    value_to_future: List[int] = []
    for child in meta:
        name = _local(child.tag)
        if name == "futureMetadata" and child.attrib.get("name") == "XLRICHVALUE":
            for bk in child:
                if _local(bk.tag) != "bk":
                    continue
                rvb_i = 0
                for node in bk.iter():
                    if _local(node.tag) == "rvb" and "i" in node.attrib:
                        rvb_i = int(node.attrib["i"])
                        break
                future_indices.append(rvb_i)
        elif name == "valueMetadata":
            for bk in child:
                if _local(bk.tag) != "bk":
                    continue
                future_i = 0
                for rc in bk:
                    if _local(rc.tag) == "rc" and rc.attrib.get("v") is not None:
                        future_i = int(rc.attrib["v"])
                        break
                value_to_future.append(future_i)
    mapping: Dict[int, int] = {}
    for vm, future_i in enumerate(value_to_future, start=1):
        if 0 <= future_i < len(future_indices):
            mapping[vm] = future_indices[future_i]
        else:
            mapping[vm] = future_i
    return mapping


def _sheet_paths(zf: zipfile.ZipFile) -> List[str]:
    wb = _read_xml(zf, "xl/workbook.xml")
    rels = _rel_targets(zf, "xl/_rels/workbook.xml.rels")
    if wb is None:
        return ["xl/worksheets/sheet1.xml"]
    paths = []
    for child in wb:
        if _local(child.tag) != "sheets":
            continue
        for sheet in child:
            if _local(sheet.tag) != "sheet":
                continue
            target = rels.get(_attr(sheet, "id"), "")
            if not target:
                continue
            path = target if target.startswith("xl/") else _norm_zip_path(f"xl/{target}")
            paths.append(path)
    return paths or ["xl/worksheets/sheet1.xml"]


def _rich_data_row_images(zf: zipfile.ZipFile) -> Dict[int, List[bytes]]:
    images = _rich_value_images(zf)
    vm_map = _vm_to_rich_index(zf)
    if not images or not vm_map:
        return {}
    out: Dict[int, List[bytes]] = {}
    for sheet_path in _sheet_paths(zf):
        root = _read_xml(zf, sheet_path)
        if root is None:
            continue
        sheet_data = next((c for c in root if _local(c.tag) == "sheetData"), None)
        if sheet_data is None:
            continue
        for row_el in sheet_data:
            if _local(row_el.tag) != "row":
                continue
            for cell in row_el:
                if _local(cell.tag) != "c" or not cell.attrib.get("vm"):
                    continue
                try:
                    rich_i = vm_map.get(int(cell.attrib["vm"]))
                except ValueError:
                    continue
                if rich_i is None or not (0 <= rich_i < len(images)) or not images[rich_i]:
                    continue
                row = _cell_row(cell.attrib.get("r", ""))
                if row is None or row < 2:
                    continue
                out.setdefault(row, []).append(images[rich_i])
    return out


def _floating_row_images(path: Path) -> Dict[int, List[bytes]]:
    try:
        from openpyxl import load_workbook
    except Exception:
        return {}
    try:
        wb = load_workbook(path, data_only=False)
    except Exception:
        return {}
    out: Dict[int, List[bytes]] = {}
    try:
        for ws in wb.worksheets:
            for img in getattr(ws, "_images", None) or []:
                anchor = getattr(img, "anchor", None)
                fr = getattr(anchor, "_from", None) if anchor is not None else None
                if fr is None or getattr(fr, "row", None) is None:
                    continue
                row = int(fr.row) + 1
                if row < 2:
                    continue
                data = None
                getter = getattr(img, "_data", None)
                if callable(getter):
                    try:
                        data = getter()
                    except Exception:
                        data = None
                if _looks_like_image(data or b""):
                    out.setdefault(row, []).append(data)
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return out


def load_xlsx_row_images(path: str | Path) -> Dict[int, List[bytes]]:
    """Return {excel_row_number: [image_bytes, ...]} for data rows (row 1 is header)."""
    xlsx = Path(path)
    merged: Dict[int, List[bytes]] = {}
    if not xlsx.exists():
        return merged
    with zipfile.ZipFile(xlsx) as zf:
        for row, blobs in _rich_data_row_images(zf).items():
            merged.setdefault(row, []).extend(blobs)
    for row, blobs in _floating_row_images(xlsx).items():
        merged.setdefault(row, []).extend(blobs)
    return {row: blobs for row, blobs in merged.items() if blobs}
