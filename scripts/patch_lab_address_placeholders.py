"""Patch report templates: replace hardcoded lab footer addresses with placeholders."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "templates"

PH_CN = "{{实验室地址_cn}}"
PH_EN = "{{实验室地址_en}}"

CN_ADDR_PARTS = ("上海市闵行区万芳路", "1351", "号", "上海市闵行区新骏环路", "777", "5号楼")
EN_ADDR_MARKERS = ("Wanfang Road", "No.1351", "Xinjun Ring Road", "Pinzheng (Shanghai)")


def register_namespaces(xml_bytes: bytes) -> None:
    text = xml_bytes.decode("utf-8", errors="replace")
    for match in re.finditer(r'xmlns:(\w+)="([^"]+)"', text[:5000]):
        etree.register_namespace(match.group(1), match.group(2))


def _run_text(run: etree._Element) -> str:
    return "".join(t.text or "" for t in run.findall("w:t", NS))


def _set_run_text(run: etree._Element, text: str) -> None:
    ts = run.findall("w:t", NS)
    if ts:
        ts[0].text = text
        for t in ts[1:]:
            t.text = ""
    else:
        t = etree.SubElement(run, f"{{{W}}}t")
        t.text = text


def _is_cn_address_run(text: str) -> bool:
    text = text or ""
    if not text.strip():
        return False
    return any(part in text for part in CN_ADDR_PARTS)


def _is_en_address_paragraph(full: str) -> bool:
    return any(m in full for m in EN_ADDR_MARKERS) and "Pinzheng" in full


def patch_cn_footer_paragraph(paragraph: etree._Element) -> bool:
    runs = paragraph.findall("w:r", NS)
    if not runs:
        return False
    full = "".join(_run_text(r) for r in runs)
    if "万芳路" not in full and "新骏环路" not in full:
        return False
    replaced = False
    for run in runs:
        rt = _run_text(run)
        if _is_cn_address_run(rt):
            if not replaced:
                _set_run_text(run, PH_CN)
                replaced = True
            else:
                _set_run_text(run, "")
    return replaced


def patch_en_footer_paragraph(paragraph: etree._Element) -> bool:
    full = "".join(t.text or "" for t in paragraph.findall(".//w:t", NS))
    if not _is_en_address_paragraph(full):
        return False
    runs = paragraph.findall("w:r", NS)
    if not runs:
        return False
    _set_run_text(runs[0], PH_EN)
    for run in runs[1:]:
        _set_run_text(run, "")
    return True


def patch_document_xml(xml_bytes: bytes) -> tuple[bytes, int]:
    register_namespaces(xml_bytes)
    root = etree.fromstring(xml_bytes)
    changes = 0
    for paragraph in root.findall(".//w:p", NS):
        if patch_cn_footer_paragraph(paragraph):
            changes += 1
        elif patch_en_footer_paragraph(paragraph):
            changes += 1
    if not changes:
        return xml_bytes, 0
    register_namespaces(xml_bytes)
    return (
        etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True),
        changes,
    )


def patch_template(path: Path) -> int:
    with zipfile.ZipFile(path, "r") as zin:
        names = zin.namelist()
        payloads = {name: zin.read(name) for name in names}
    new_doc, n = patch_document_xml(payloads["word/document.xml"])
    if not n:
        return 0
    payloads["word/document.xml"] = new_doc
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, payloads[name])
    return n


def main() -> None:
    targets = [
        "template_zh.docx",
        "template_en.docx",
        "template_ze.docx",
        "template_zh_4sign.docx",
        "template_en_4sign.docx",
        "template_ze_4sign.docx",
    ]
    for name in targets:
        path = TEMPLATES / name
        if not path.is_file():
            print("skip missing", name)
            continue
        n = patch_template(path)
        print(f"patched {name}: {n} paragraph(s)")


if __name__ == "__main__":
    main()
