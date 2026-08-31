"""Locate 申请单 Excel and 报价单 PDF under 1.接样组."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

SAMPLE_DIR_NAME = "1.接样组"
_PROJECT_ID_RE = re.compile(r"(A\d{8,})", re.IGNORECASE)
# CTI 报价单号前缀，常见于 ``SZV2607242479701 客户--项目.pdf`` 这类文件名。
_CTI_QUOTE_NO_RE = re.compile(r"^SZV\d+", re.IGNORECASE)


def project_id_match_tokens(project_id: str) -> list[str]:
    """IDs that may appear on the 申请单 filename.

    Folder/project ids are often 14 chars (申请单号 + 两位序号);
    the Excel is typically the 12-char 申请单号.
    """
    raw = (project_id or "").strip().upper()
    if not raw:
        return []
    m = _PROJECT_ID_RE.search(raw)
    if not m:
        return [raw]
    full = m.group(1).upper()
    tokens = [full]
    if len(full) > 12:
        tokens.append(full[:12])
    return tokens


def _stem_match_key(stem: str, tokens: list[str]) -> Optional[tuple]:
    """Sort key if *stem* belongs to this project; else None.

    Exact stem wins over ``A2260…--申请表更新``. A longer digit run
    (another project's id) does not match a shorter token.
    """
    text = stem.upper()
    for index, token in enumerate(tokens):
        if text == token:
            return (0, index, len(text))
        if (
            text.startswith(token)
            and len(text) > len(token)
            and not text[len(token)].isdigit()
        ):
            return (1, index, len(text))
    return None


def _sample_dir(project_path: Path) -> Path:
    return Path(project_path) / SAMPLE_DIR_NAME


def _iter_xlsx(sample_dir: Path):
    for path in sample_dir.iterdir():
        if not path.is_file():
            continue
        if path.name.startswith("~"):
            continue
        if path.suffix.lower() == ".xlsx":
            yield path


def find_application_excel(project_path: Path, project_id: str) -> Optional[Path]:
    sample_dir = _sample_dir(project_path)
    tokens = project_id_match_tokens(project_id)
    if not tokens or not sample_dir.is_dir():
        return None
    ranked: list[tuple] = []
    for path in _iter_xlsx(sample_dir):
        key = _stem_match_key(path.stem, tokens)
        if key is not None:
            ranked.append((key, path.name, path))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def _quotation_name_match(name: str) -> bool:
    if "报价单" in name:
        return True
    stem = Path(name).stem.strip()
    first_token = stem.split()[0] if stem else ""
    return bool(_CTI_QUOTE_NO_RE.match(first_token))


def find_quotation_pdf(project_path: Path) -> Optional[Path]:
    sample_dir = _sample_dir(project_path)
    if not sample_dir.is_dir():
        return None

    from src.parsers.pdf_parser import QuotationParser

    fallback: list[Path] = []
    for path in sample_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        if _quotation_name_match(path.name):
            return path
        fallback.append(path)

    for path in fallback:
        if QuotationParser.is_quotation_pdf(str(path)):
            return path
    return None


def find_sample_files(
    project_path: Path, project_id: str
) -> Tuple[Optional[Path], Optional[Path]]:
    return find_application_excel(project_path, project_id), find_quotation_pdf(
        project_path
    )
