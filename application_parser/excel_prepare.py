"""Prepare Excel uploads for openpyxl: strip known non-OOXML quirks before parsing.

Mirrors ``doc_convert.prepare_report_upload``: fix at the upload boundary so the
audit / parser pipeline only sees a workbook openpyxl can load.
"""

from __future__ import annotations

import io
import os
import zipfile
from typing import Tuple
from xml.etree import ElementTree as ET

import openpyxl

from application_parser.encoding_io import normalize_upload_filename

# openpyxl DataValidation.type whitelist (OOXML); WPS may emit type="any" for prompts.
_ALLOWED_DV_TYPES = frozenset(
    {"custom", "list", "decimal", "time", "whole", "textLength", "date"}
)
_SSML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS = {"m": _SSML}


class ExcelPrepareError(RuntimeError):
    """Raised when an Excel upload cannot be normalized for openpyxl."""


def excel_upload_extension(filename: str) -> str:
    return os.path.splitext((filename or "").lower())[1]


def is_xlsx_filename(filename: str) -> bool:
    return excel_upload_extension(filename) == ".xlsx"


def _register_ooxml_namespaces() -> None:
    ET.register_namespace("", _SSML)
    ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
    ET.register_namespace("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006")
    ET.register_namespace("x14", "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main")
    ET.register_namespace("xr", "http://schemas.microsoft.com/office/spreadsheetml/2014/revision")
    ET.register_namespace("xr2", "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2")
    ET.register_namespace("xr3", "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3")


def _strip_unsupported_data_validations(sheet_xml: bytes) -> Tuple[bytes, int]:
    """Remove dataValidation nodes whose type is outside openpyxl's whitelist."""
    _register_ooxml_namespaces()
    root = ET.fromstring(sheet_xml)
    removed = 0
    for dvs in root.findall("m:dataValidations", _NS):
        for dv in list(dvs.findall("m:dataValidation", _NS)):
            dv_type = dv.attrib.get("type")
            if dv_type is not None and dv_type not in _ALLOWED_DV_TYPES:
                dvs.remove(dv)
                removed += 1
        remaining = list(dvs.findall("m:dataValidation", _NS))
        if not remaining:
            root.remove(dvs)
        else:
            dvs.set("count", str(len(remaining)))
    if removed == 0:
        return sheet_xml, 0
    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return out, removed


def sanitize_xlsx_bytes(file_bytes: bytes) -> Tuple[bytes, int]:
    """Rewrite xlsx zip: drop unsupported dataValidations. Returns (bytes, removed_count)."""
    if not file_bytes:
        return file_bytes, 0
    try:
        zin = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ExcelPrepareError("不是有效的 .xlsx（ZIP）文件") from exc

    removed_total = 0
    buf = io.BytesIO()
    with zin, zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            name = info.filename
            if (
                name.startswith("xl/worksheets/sheet")
                and name.endswith(".xml")
                and "/_rels/" not in name
            ):
                data, n = _strip_unsupported_data_validations(data)
                removed_total += n
            # Preserve ZipInfo metadata where possible (date_time etc.).
            out_info = zipfile.ZipInfo(filename=name, date_time=info.date_time)
            out_info.compress_type = zipfile.ZIP_DEFLATED
            if info.external_attr:
                out_info.external_attr = info.external_attr
            zout.writestr(out_info, data)
    return buf.getvalue(), removed_total


def _workbook_loads(file_bytes: bytes) -> bool:
    try:
        openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        return True
    except Exception:
        return False


def prepare_excel_upload(file_bytes: bytes, filename: str) -> Tuple[bytes, str]:
    """Normalize application/outline uploads for openpyxl.

    Pass through when already loadable. Otherwise strip known-bad dataValidation
    types (e.g. WPS ``type="any"`` prompt-only rules) and re-check.
    """
    name = normalize_upload_filename(filename) or "workbook.xlsx"
    if not is_xlsx_filename(name):
        return file_bytes, name
    if not file_bytes:
        raise ExcelPrepareError(f"空的 Excel 文件：{name}")

    if _workbook_loads(file_bytes):
        return file_bytes, name

    try:
        cleaned, removed = sanitize_xlsx_bytes(file_bytes)
    except ExcelPrepareError:
        raise
    except Exception as exc:
        raise ExcelPrepareError(f"无法预处理 Excel：{name}（{exc}）") from exc

    if removed == 0:
        raise ExcelPrepareError(
            f"无法读取 Excel：{name}。"
            "文件可能已损坏或含有 openpyxl 不支持的内容；请用 Excel 另存为标准 .xlsx 后再上传。"
        )

    if not _workbook_loads(cleaned):
        raise ExcelPrepareError(
            f"已清理非标准数据验证后仍无法读取 Excel：{name}。"
            "请用 Excel 打开并另存为标准 .xlsx 后再上传。"
        )
    return cleaned, name
