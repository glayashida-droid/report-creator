"""Refresh TOC/page fields in an exported .docx via local Microsoft Word.

python-docx cannot recompute a TOC. The previous approach only set
``w:updateFields``, which makes Word ask on every open (and Mac Word often
never clears the flag). After export we drive Word to update fields, then
strip the flag from the package so the next open is quiet.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from docx import Document
from docx.oxml.ns import qn

from src.generators.elp_docx import (
    iter_body_children,
    mark_fields_for_update,
    paragraph_style_name,
    wrap_paragraph,
)

_MAC_WORD_APP = Path("/Applications/Microsoft Word.app")
_UPDATE_FIELDS_RE = re.compile(
    rb"<w:updateFields\b[^/]*/>|<w:updateFields\b[^>]*>\s*</w:updateFields>",
    re.IGNORECASE,
)
_DIRTY_ATTR_RE = re.compile(rb'\s+w:dirty="(?:true|1)"', re.IGNORECASE)

_MAC_SCRIPT = r'''
on run argv
    set posixPath to item 1 of argv
    set docFile to POSIX file posixPath as alias
    tell application "Microsoft Word"
        set wasRunning to running
        set oldAlerts to display alerts
        set display alerts to alerts none
        set oldUpdateLinks to update links at open
        set update links at open to false
        try
            open docFile
            set theDoc to active document
            try
                set tocCount to count of tables of contents of theDoc
                repeat with i from 1 to tocCount
                    update table of contents i of theDoc
                end repeat
            end try
            try
                set fieldCount to count of fields of theDoc
                repeat with i from 1 to fieldCount
                    update field field i of theDoc
                end repeat
            end try
            save theDoc
            close theDoc saving yes
        on error errMsg number errNum
            set display alerts to oldAlerts
            set update links at open to oldUpdateLinks
            error errMsg number errNum
        end try
        set display alerts to oldAlerts
        set update links at open to oldUpdateLinks
        if (not wasRunning) and ((count of documents) is 0) then
            quit
        end if
    end tell
end run
'''

_WIN_SCRIPT = r'''
param([Parameter(Mandatory=$true)][string]$DocPath)
$ErrorActionPreference = 'Stop'
$wdDoNotSaveChanges = 0
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $word.Options.UpdateLinksAtOpen = $false
} catch {}
$doc = $null
try {
    $doc = $word.Documents.Open($DocPath, $false, $false, $false)
    foreach ($toc in @($doc.TablesOfContents)) {
        $toc.Update() | Out-Null
    }
    $doc.Fields.Update() | Out-Null
    foreach ($section in @($doc.Sections)) {
        foreach ($hdr in @($section.Headers)) {
            try { $hdr.Range.Fields.Update() | Out-Null } catch {}
        }
        foreach ($ftr in @($section.Footers)) {
            try { $ftr.Range.Fields.Update() | Out-Null } catch {}
        }
    }
    $doc.Save() | Out-Null
    $wdDoNotSaveChanges = 0
    $doc.Close($wdDoNotSaveChanges) | Out-Null
    $doc = $null
} finally {
    if ($null -ne $doc) {
        try { $doc.Close($wdDoNotSaveChanges) | Out-Null } catch {}
    }
    if ($word.Documents.Count -eq 0) {
        $word.Quit() | Out-Null
    }
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
'''


def heading_texts(doc) -> List[str]:
    texts: List[str] = []
    for child in iter_body_children(doc):
        if child.tag != qn("w:p"):
            continue
        paragraph = wrap_paragraph(child, doc)
        if not paragraph_style_name(paragraph).startswith("Heading"):
            continue
        text = (paragraph.text or "").strip()
        if text:
            texts.append(text)
    return texts


def toc_result_texts(doc) -> List[str]:
    texts: List[str] = []
    for paragraph in doc.element.body.iter(qn("w:p")):
        instrs = [node.text or "" for node in paragraph.iter(qn("w:instrText"))]
        joined = " ".join(instrs).upper()
        if "TOC" not in joined and "PAGEREF" not in joined:
            continue
        visible = "".join((node.text or "") for node in paragraph.iter(qn("w:t"))).strip()
        if visible:
            texts.append(visible)
    return texts


def toc_is_stale(doc) -> bool:
    """True when the cached TOC still lists headings that are no longer in the body."""
    headings = heading_texts(doc)
    if not headings:
        return False
    toc_lines = toc_result_texts(doc)
    if not toc_lines:
        return False
    unmatched = 0
    for line in toc_lines:
        if not any(heading in line for heading in headings):
            unmatched += 1
    return unmatched > 2


def skip_word_automation() -> bool:
    if os.environ.get("REPORT_CREATOR_REFRESH_WORD"):
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def word_app_available() -> bool:
    if sys.platform == "darwin":
        return _MAC_WORD_APP.is_dir()
    if sys.platform == "win32":
        return True
    return False


def strip_field_update_flags_in_package(path: str | Path) -> None:
    """Remove updateFields / dirty marks via zip so Word's TOC XML is not round-tripped."""
    src = Path(path)
    tmp = src.with_name(src.stem + ".fields-strip.docx")
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/settings.xml":
                data = _UPDATE_FIELDS_RE.sub(b"", data)
            elif item.filename == "word/document.xml":
                data = _DIRTY_ATTR_RE.sub(b"", data)
            zout.writestr(item, data)
    tmp.replace(src)


def refresh_word_fields(path: str | Path, *, timeout: int = 180) -> bool:
    """Open the document in Microsoft Word, update TOC/fields, and save. Return True on success."""
    if skip_word_automation() or not word_app_available():
        return False
    posix = str(Path(path).resolve())
    try:
        if sys.platform == "darwin":
            completed = subprocess.run(
                ["osascript", "-", posix],
                input=_MAC_SCRIPT,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        elif sys.platform == "win32":
            completed = _run_windows_word(posix, timeout)
        else:
            return False
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    time.sleep(0.4)
    return Path(posix).is_file()


def finalize_exported_fields(
    path: str | Path,
    *,
    refresher: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Refresh fields with Word when possible; otherwise ask Word to prompt on open.

    Returns True when Word updated the TOC and the open-time prompt was stripped.
    """
    target = str(Path(path))
    hook = refresher if refresher is not None else refresh_word_fields
    if hook(target):
        try:
            stale = toc_is_stale(Document(target))
        except Exception:
            stale = True
        if stale:
            _mark_for_open_update(target)
            return False
        strip_field_update_flags_in_package(target)
        return True
    _mark_for_open_update(target)
    return False


def _mark_for_open_update(path: str) -> None:
    doc = Document(path)
    mark_fields_for_update(doc)
    doc.save(path)


def _run_windows_word(posix: str, timeout: int) -> subprocess.CompletedProcess:
    script_path = Path(posix).with_name(Path(posix).stem + ".refresh-fields.ps1")
    script_path.write_text(_WIN_SCRIPT, encoding="utf-8")
    try:
        return subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                posix,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        script_path.unlink(missing_ok=True)
