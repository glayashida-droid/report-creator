"""Save a clean ELP Word template: drop review comments, keep blue slots and layout."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "templates" / "report_templates"
SOURCE_NAME = "ELP 零部件试验报告模板 - 更新中.docx"
DEST_NAME = "template_elp_zh.docx"

DROP_PARTS = {
    "word/comments.xml",
    "word/commentsExtended.xml",
    "word/commentsIds.xml",
    "word/commentsExtensible.xml",
    "word/people.xml",
}

COMMENT_MARK_RE = re.compile(
    r"<w:commentRangeStart\b[^>]*/>"
    r"|<w:commentRangeEnd\b[^>]*/>"
    r"|<w:commentReference\b[^>]*/>"
    r"|<w:commentRangeStart\b[^>]*>.*?</w:commentRangeStart>"
    r"|<w:commentRangeEnd\b[^>]*>.*?</w:commentRangeEnd>"
    r"|<w:commentReference\b[^>]*>.*?</w:commentReference>",
    re.DOTALL,
)

CONTENT_TYPE_DROP_RE = re.compile(
    r'<Override\b[^>]*PartName="/word/'
    r'(?:comments(?:Extended|Ids|Extensible)?|people)\.xml"[^>]*/>\s*',
    re.IGNORECASE,
)

REL_DROP_RE = re.compile(
    r'<Relationship\b[^>]*Type="[^"]*(?:comments(?:Extended|Ids|Extensible)?|people)"[^>]*/>\s*',
    re.IGNORECASE,
)


def _strip_document_xml(raw: bytes) -> bytes:
    text = raw.decode("utf-8")
    text = COMMENT_MARK_RE.sub("", text)
    return text.encode("utf-8")


def _strip_content_types(raw: bytes) -> bytes:
    return CONTENT_TYPE_DROP_RE.sub("", raw.decode("utf-8")).encode("utf-8")


def _strip_rels(raw: bytes) -> bytes:
    return REL_DROP_RE.sub("", raw.decode("utf-8")).encode("utf-8")


def strip_elp_template(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(
        dest, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            name = item.filename
            if name in DROP_PARTS or name.startswith("word/comments"):
                continue
            data = zin.read(name)
            if name == "word/document.xml":
                data = _strip_document_xml(data)
            elif name.endswith(".xml") and name.startswith("word/") and name != "word/comments.xml":
                if b"commentRange" in data or b"commentReference" in data:
                    data = _strip_document_xml(data)
            elif name == "[Content_Types].xml":
                data = _strip_content_types(data)
            elif name.endswith(".rels") and b"comments" in data.lower():
                data = _strip_rels(data)
            zout.writestr(item, data)


def main() -> None:
    source = TEMPLATES / SOURCE_NAME
    dest = TEMPLATES / DEST_NAME
    if not source.is_file():
        raise SystemExit(f"missing source template: {source}")
    strip_elp_template(source, dest)
    print(f"wrote {dest.relative_to(REPO)} from {source.name}")


if __name__ == "__main__":
    main()
