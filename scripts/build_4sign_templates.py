"""Build template_*_4sign.docx from base templates + ze multi-sign table.

Uses lxml and preserves original OOXML namespace prefixes so Word can open files.
"""

from __future__ import annotations

import copy
import re
import shutil
import zipfile
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)
NS = {"w": W}

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "templates"
SIGN_SOURCE = TEMPLATES / "template_ze.docx"
SIGN_SOURCE_IDX = 8

TARGETS = [
    ("template_zh.docx", "template_zh_4sign.docx", 9),
    ("template_en.docx", "template_en_4sign.docx", 9),
    ("template_ze.docx", "template_ze_4sign.docx", 8),
]

JPEG_DEFAULT = '<Default Extension="jpeg" ContentType="image/jpeg"/>'


def register_namespaces_from_xml(xml_bytes: bytes) -> None:
    text = xml_bytes.decode("utf-8", errors="replace")
    for match in re.finditer(r'xmlns:(\w+)="([^"]+)"', text[:5000]):
        etree.register_namespace(match.group(1), match.group(2))


def table_text(tbl: etree._Element) -> str:
    return "".join(tbl.itertext())


def collect_embed_rids(element: etree._Element) -> list[str]:
    rids: list[str] = []
    seen = set()
    for el in element.iter():
        for attr, val in el.attrib.items():
            if val and (attr.endswith("embed") or attr.endswith("link")):
                if val not in seen:
                    seen.add(val)
                    rids.append(val)
    return rids


def parse_rel_map(rels_bytes: bytes) -> dict[str, dict[str, str]]:
    root = etree.fromstring(rels_bytes)
    rels: dict[str, dict[str, str]] = {}
    for rel in root:
        rels[rel.get("Id") or ""] = {
            "Type": rel.get("Type") or "",
            "Target": rel.get("Target") or "",
        }
    return rels


def max_rid_in_rels(rels_text: str) -> int:
    nums = [int(m.group(1)) for m in re.finditer(r'Id="rId(\d+)"', rels_text)]
    return max(nums) if nums else 0


def next_media_name(existing: set[str], src_name: str) -> str:
    suffix = Path(src_name).suffix.lower()
    n = 1
    while True:
        candidate = f"media/sign{n}{suffix}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
        n += 1


def ensure_jpeg_content_type(content_types: bytes) -> bytes:
    text = content_types.decode("utf-8")
    if 'Extension="jpeg"' in text or 'Extension="jpg"' in text:
        return content_types
    insert_at = text.find("</Types>")
    if insert_at == -1:
        return content_types
    updated = text[:insert_at] + JPEG_DEFAULT + text[insert_at:]
    return updated.encode("utf-8")


def append_relationships(rels_text: str, entries: list[tuple[str, str, str]]) -> str:
    block = "".join(
        f'<Relationship Id="{rid}" Type="{typ}" Target="{target}"/>'
        for rid, typ, target in entries
    )
    return rels_text.replace("</Relationships>", block + "</Relationships>", 1)


def remap_rids(element: etree._Element, mapping: dict[str, str]) -> None:
    for el in element.iter():
        for attr, val in list(el.attrib.items()):
            if val in mapping:
                el.set(attr, mapping[val])


def clone_signature_table(base_name: str, out_name: str, target_sign_idx: int) -> None:
    base_path = TEMPLATES / base_name
    out_path = TEMPLATES / out_name

    if base_name == "template_ze.docx":
        shutil.copy2(base_path, out_path)
        print(f"created {out_name} (copy of {base_name})")
        return

    with zipfile.ZipFile(SIGN_SOURCE, "r") as zsrc:
        ze_doc_bytes = zsrc.read("word/document.xml")
        ze_rels_map = parse_rel_map(zsrc.read("word/_rels/document.xml.rels"))
        register_namespaces_from_xml(ze_doc_bytes)
        ze_root = etree.fromstring(ze_doc_bytes)
        sign_tbl = copy.deepcopy(ze_root.find("w:body", NS)[SIGN_SOURCE_IDX])
        sign_rids = collect_embed_rids(sign_tbl)

    shutil.copy2(base_path, out_path)
    with zipfile.ZipFile(out_path, "r") as zin:
        names = zin.namelist()
        payloads = {name: zin.read(name) for name in names}

    tgt_doc_bytes = payloads["word/document.xml"]
    register_namespaces_from_xml(tgt_doc_bytes)
    tgt_root = etree.fromstring(tgt_doc_bytes)
    tgt_body = tgt_root.find("w:body", NS)

    rels_text = payloads["word/_rels/document.xml.rels"].decode("utf-8")
    next_rid = max_rid_in_rels(rels_text) + 1
    rel_entries: list[tuple[str, str, str]] = []
    rid_mapping: dict[str, str] = {}
    existing_media = {n.split("/", 1)[1] for n in names if n.startswith("word/media/")}
    needs_jpeg = False

    with zipfile.ZipFile(SIGN_SOURCE, "r") as zsrc:
        for old_rid in sign_rids:
            info = ze_rels_map.get(old_rid)
            if not info or info["Type"] != IMAGE_REL:
                continue
            src_target = info["Target"]
            src_media_path = "word/" + src_target
            media_bytes = zsrc.read(src_media_path)
            new_target = next_media_name(existing_media, src_target)
            if new_target.endswith(".jpeg") or new_target.endswith(".jpg"):
                needs_jpeg = True
            new_media_path = "word/" + new_target
            payloads[new_media_path] = media_bytes
            new_rid = f"rId{next_rid}"
            next_rid += 1
            rid_mapping[old_rid] = new_rid
            rel_entries.append((new_rid, IMAGE_REL, new_target))

    remap_rids(sign_tbl, rid_mapping)
    tgt_body[target_sign_idx] = sign_tbl

    register_namespaces_from_xml(tgt_doc_bytes)
    payloads["word/document.xml"] = etree.tostring(
        tgt_root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=True,
    )
    payloads["word/_rels/document.xml.rels"] = append_relationships(
        rels_text, rel_entries
    ).encode("utf-8")
    if needs_jpeg:
        payloads["[Content_Types].xml"] = ensure_jpeg_content_type(
            payloads["[Content_Types].xml"]
        )

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        written = set()
        for name in names:
            zout.writestr(name, payloads[name])
            written.add(name)
        for name, data in payloads.items():
            if name not in written:
                zout.writestr(name, data)

    print(f"created {out_name} from {base_name} with ze signature table")


def validate_docx(path: Path) -> None:
    with zipfile.ZipFile(path) as z:
        doc = z.read("word/document.xml")
        rels = z.read("word/_rels/document.xml.rels")
    assert b"<w:document" in doc, f"{path.name}: missing w:document root"
    assert b"ns0:" not in doc, f"{path.name}: bad namespace prefix in document.xml"
    assert b"Relationships xmlns=" in rels, f"{path.name}: bad relationships root"
    assert b"ns0:" not in rels, f"{path.name}: bad namespace prefix in rels"


def main() -> None:
    for base, out, idx in TARGETS:
        clone_signature_table(base, out, idx)
        validate_docx(TEMPLATES / out)

    for out in [name for _, name, _ in TARGETS]:
        with zipfile.ZipFile(TEMPLATES / out) as z:
            register_namespaces_from_xml(z.read("word/document.xml"))
            root = etree.fromstring(z.read("word/document.xml"))
        body = root.find("w:body", NS)
        for i, child in enumerate(body):
            if child.tag == f"{{{W}}}tbl":
                text = table_text(child)
                if any(k in text for k in ["Written", "Approved", "Inspected", "编制", "审核", "批准"]):
                    print("verify", out, "tbl", i, re.sub(r"\s+", " ", text)[:120])


if __name__ == "__main__":
    main()
