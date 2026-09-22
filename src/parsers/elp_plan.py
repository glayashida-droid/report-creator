"""Find and parse a Geely ELP test-plan PDF under 1.接样组."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SAMPLE_DIR_NAME = "1.接样组"
# P166-ELP-TP(副仪表板开关组)-2026-0001  or  L946-A1-ELP-TP-2026-0045
PLAN_NO_RE = re.compile(
    r"("
    r"[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*"
    r"-ELP-TP"
    r"(?:\s*[（(][^)）]+[)）])?"
    r"\s*-\s*\d{4}\s*-\s*\d+"
    r")",
    re.IGNORECASE,
)
CHAPTER6_BASIC = "basic"
CHAPTER6_FUNCTION_CLASS = "function_class"
CHAPTER6_WORK_MODES = "work_modes"
CHAPTER6_MONITOR = "monitor"
CHAPTER6_STATES = "states"
_CHAPTER6_IMAGE_DPI = 300
_RULE_SNAP_PT = 8.0
_CROP_PAD_PT = 3.0
_HEADER_VEHICLE_RE = re.compile(r"([A-Za-z0-9]+)\s*车型")
_PHOTO_INDEX_RE = re.compile(r"^图片\s*\d+\s*[:：]\s*")
_SPACE_RE = re.compile(r"\s+")


def normalize_elp_name(text: str) -> str:
    value = (text or "").replace("Pin", "PIN").replace("pin", "PIN")
    return _SPACE_RE.sub("", value).casefold()


def elp_names_match(left: str, right: str) -> bool:
    a = normalize_elp_name(left)
    b = normalize_elp_name(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    a2 = a.replace("和", "")
    b2 = b.replace("和", "")
    return a2 == b2 or a2 in b2 or b2 in a2


def caption_from_stem(stem: str) -> str:
    text = (stem or "").strip()
    stripped = _PHOTO_INDEX_RE.sub("", text).strip()
    return stripped or text


def lookup_work_mode(mapping: Dict[str, str], test_name: str) -> str:
    needle = (test_name or "").strip()
    if not needle:
        return ""
    direct = mapping.get(needle)
    if direct:
        return direct
    for key, value in mapping.items():
        if elp_names_match(needle, key):
            return value
    return ""


@dataclass
class ElpPlan:
    product_name: str = ""
    vehicle_code: str = ""
    part_no: str = ""
    hw_version: str = ""
    sw_version: str = ""
    plan_no: str = ""
    basic_ticks: Dict[str, List[str]] = field(default_factory=dict)
    extra_info: Dict[str, str] = field(default_factory=dict)
    basic_info_rows: List[List[str]] = field(default_factory=list)
    work_mode_defs: List[Tuple[str, str]] = field(default_factory=list)
    work_mode_notes: str = ""
    function_class_rows: List[List[str]] = field(default_factory=list)
    monitor_rows: List[Tuple[str, str, str]] = field(default_factory=list)
    function_states: List[Tuple[str, str]] = field(default_factory=list)
    test_work_modes: Dict[str, str] = field(default_factory=dict)
    chapter6_images: Dict[str, bytes] = field(default_factory=dict)


def elp_plan_filename_score(name: str) -> int:
    """Rank a PDF filename as an ELP test plan. Zero means not a plan by name."""
    if not name or "报价单" in name:
        return 0
    score = 0
    upper = name.upper()
    if "ELP" in upper:
        score += 3
    if "测试计划" in name:
        score += 2
    return score


def is_elp_plan_filename(name: str) -> bool:
    return elp_plan_filename_score(name) > 0


def is_elp_plan_attachment(path: Path) -> bool:
    """True for an ELP test-plan PDF living under 1.接样组 (filename only)."""
    candidate = Path(path)
    if candidate.suffix.lower() != ".pdf":
        return False
    if SAMPLE_DIR_NAME not in candidate.parts:
        return False
    return is_elp_plan_filename(candidate.name)


def find_elp_plan_pdf(project_path: Optional[Path]) -> Optional[Path]:
    if project_path is None:
        return None
    sample_dir = Path(project_path) / SAMPLE_DIR_NAME
    if not sample_dir.is_dir():
        return None
    pdfs = [
        path
        for path in sample_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".pdf"
        and not path.name.startswith("~")
        and not path.name.startswith(".")
    ]
    ranked: List[Tuple[int, str, Path]] = []
    for path in pdfs:
        score = elp_plan_filename_score(path.name)
        if score:
            ranked.append((score, path.name, path))
    if ranked:
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return ranked[0][2]
    for path in pdfs:
        if _pdf_looks_like_elp(path):
            return path
    return None


def resolve_elp_plan_pdf(
    local_path: Optional[Path],
    source_path: Optional[Path] = None,
) -> Optional[Path]:
    """Prefer the local mirror copy; fall back to the source project folder."""
    found = find_elp_plan_pdf(local_path)
    if found is not None:
        return found
    if source_path is None or source_path == local_path:
        return None
    return find_elp_plan_pdf(source_path)


def _pdf_looks_like_elp(path: Path) -> bool:
    try:
        import pdfplumber
    except ImportError:
        return False
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:4]:
                text = page.extract_text() or ""
                if "ELP" in text.upper() and "测试计" in text:
                    return True
    except Exception:
        return False
    return False


def extract_plan_number_from_text(text: str) -> str:
    normalized = (text or "").replace("－", "-").replace("–", "-").replace("—", "-")
    compact = re.sub(r"\s+", "", normalized)
    for blob in (normalized, compact):
        match = PLAN_NO_RE.search(blob)
        if match:
            return re.sub(r"\s+", "", match.group(1))
    return ""


def tesseract_cmd() -> Optional[str]:
    """Locate tesseract even when GUI apps do not inherit Homebrew PATH."""
    found = shutil.which("tesseract")
    if found:
        return found
    candidates = (
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    )
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return str(path)
    return None


def ocr_elp_plan_number(pdf_path: Path) -> str:
    """OCR page 1 of the plan PDF. Empty string when tesseract is unavailable."""
    image = _cover_image(pdf_path)
    if image is None:
        return ""
    text = _ocr_image_text(image)
    return extract_plan_number_from_text(text)


def _cover_image(pdf_path: Path):
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            if not pdf.pages:
                return None
            return pdf.pages[0].to_image(resolution=200).original
    except Exception:
        return None


def _ocr_image_text(image) -> str:
    cmd = tesseract_cmd()
    try:
        import pytesseract

        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        return pytesseract.image_to_string(image, lang="chi_sim+eng") or ""
    except Exception:
        pass
    if not cmd:
        return ""
    try:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        payload = buf.getvalue()
        completed = subprocess.run(
            [cmd, "stdin", "stdout", "-l", "chi_sim+eng"],
            input=payload,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if completed.returncode == 0:
            return (completed.stdout or b"").decode("utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def parse_elp_plan(pdf_path: Optional[Path], *, ocr_cover: bool = True) -> ElpPlan:
    plan = ElpPlan()
    if pdf_path is None or not Path(pdf_path).is_file():
        return plan
    path = Path(pdf_path)
    try:
        import pdfplumber
    except ImportError:
        if ocr_cover:
            plan.plan_no = ocr_elp_plan_number(path)
        return plan

    from concurrent.futures import ThreadPoolExecutor

    ocr_no = ""
    tables: List[List[List[str]]] = []
    header_text = ""
    cover_text = ""
    notes_chunks: List[str] = []
    images: Dict[str, bytes] = {}

    def _extract_tables() -> Tuple[str, str, List[str], List[List[List[str]]], Dict[str, bytes]]:
        header = ""
        cover = ""
        notes: List[str] = []
        found: List[List[List[str]]] = []
        shots: Dict[str, bytes] = {}
        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if index == 0:
                    cover = text
                if not header:
                    header = text
                if "备注" in text and "mode 3.1" in text.replace(" ", "").casefold():
                    notes.append(text)
                for raw in page.extract_tables() or []:
                    found.append(_clean_table(raw))
                _collect_chapter6_images(page, shots)
        return cover, header, notes, found, shots

    if ocr_cover:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ocr_fut = pool.submit(ocr_elp_plan_number, path)
            cover_text, header_text, notes_chunks, tables, images = _extract_tables()
            ocr_no = ocr_fut.result() or ""
    else:
        cover_text, header_text, notes_chunks, tables, images = _extract_tables()

    _fill_from_header(plan, header_text)
    _fill_from_tables(plan, tables)
    plan.work_mode_notes = _extract_work_mode_notes(notes_chunks)
    plan.chapter6_images = images
    plan.plan_no = extract_plan_number_from_text(cover_text)
    if ocr_cover and not plan.plan_no:
        plan.plan_no = ocr_no
    return plan


def _clean_table(raw: Sequence[Sequence[Optional[str]]]) -> List[List[str]]:
    rows: List[List[str]] = []
    for row in raw:
        rows.append(
            [re.sub(r"\s+", " ", str(cell or "").replace("\n", " ")).strip() for cell in row]
        )
    return rows


def _fill_from_header(plan: ElpPlan, text: str) -> None:
    match = _HEADER_VEHICLE_RE.search(text or "")
    if match:
        plan.vehicle_code = match.group(1).strip()
    product = ""
    header_match = re.search(
        r"[A-Za-z0-9]+\s*车型(.+?)产品\s*ELP", text or ""
    )
    if header_match:
        product = header_match.group(1).strip()
    plan.product_name = product


def _fill_from_tables(plan: ElpPlan, tables: Sequence[Sequence[Sequence[str]]]) -> None:
    for table in tables:
        if not table:
            continue
        first = _row_join(table[0])
        if first.startswith("电子电器组件种类"):
            plan.basic_info_rows = [list(row) for row in table]
            _parse_basic_info(plan, table)
        elif "吉利零部件号" in first and "硬件版本" in first:
            _parse_hw_sw(plan, table)
        elif first.startswith("工作模式") and "定义描述" in first:
            _parse_work_mode_defs(plan, table)
        elif "产品功能分类" in first or (
            len(table) > 1 and "A类" in _row_join(table[1]) and "工作模式" in first
        ):
            _parse_function_class(plan, table)
        elif first.startswith("序号") and "功能描述" in first and "可接受范围" in first:
            if not plan.monitor_rows:
                _parse_monitor(plan, table)
        elif "测试项目" in first and "工作模式" in first:
            _parse_test_work_modes(plan, table)
        elif "功能状态" in first and "定义描述" in first:
            _parse_function_states(plan, table)


def _row_join(row: Sequence[str]) -> str:
    return "".join(row or [])


def _parse_basic_info(plan: ElpPlan, table: Sequence[Sequence[str]]) -> None:
    i = 0
    while i < len(table):
        row = table[i]
        label = (row[0] if row else "").strip()
        if label in {
            "电子电器组件种类",
            "工作类型",
            "外壳材质",
            "安装位置",
            "电源回线及搭铁方式",
        }:
            ticks: List[str] = []
            if i + 1 < len(table):
                tick_row = table[i + 1]
                limit = max(len(row), len(tick_row))
                for idx in range(1, limit):
                    mark = tick_row[idx] if idx < len(tick_row) else ""
                    option = row[idx] if idx < len(row) else ""
                    if "√" in (mark or "") and (option or "").strip():
                        ticks.append(option.strip())
            if ticks:
                plan.basic_ticks[label] = ticks
            i += 2
            continue
        if label == "更多相关信息描述" and i + 1 < len(table):
            value_row = table[i + 1]
            limit = max(len(row), len(value_row))
            for idx in range(1, limit):
                key = (row[idx] if idx < len(row) else "").strip()
                val = (value_row[idx] if idx < len(value_row) else "").strip()
                if key and val:
                    plan.extra_info[key] = val
            i += 2
            continue
        i += 1


def _parse_hw_sw(plan: ElpPlan, table: Sequence[Sequence[str]]) -> None:
    if len(table) < 2:
        return
    values = table[1]
    if len(values) >= 1:
        plan.part_no = values[0]
    if len(values) >= 2:
        plan.hw_version = values[1]
    if len(values) >= 3:
        plan.sw_version = values[2]


def _parse_work_mode_defs(plan: ElpPlan, table: Sequence[Sequence[str]]) -> None:
    rows: List[Tuple[str, str]] = []
    for row in table[1:]:
        if len(row) < 2:
            continue
        mode = (row[0] or "").strip()
        desc = (row[1] or "").strip()
        if not mode or mode.startswith("备注"):
            continue
        rows.append((mode, desc))
    if rows:
        plan.work_mode_defs = rows


def _parse_function_class(plan: ElpPlan, table: Sequence[Sequence[str]]) -> None:
    if len(table) < 3:
        return
    plan.function_class_rows = [list(row) for row in table]


def _parse_monitor(plan: ElpPlan, table: Sequence[Sequence[str]]) -> None:
    rows: List[Tuple[str, str, str]] = []
    for row in table[1:]:
        if len(row) < 3:
            continue
        seq, desc, accept = row[0], row[1], row[2]
        if not desc:
            continue
        rows.append((seq, desc, accept))
    plan.monitor_rows = rows


def _parse_test_work_modes(plan: ElpPlan, table: Sequence[Sequence[str]]) -> None:
    for row in table[1:]:
        if len(row) < 3:
            continue
        name = (row[1] or "").strip()
        mode = (row[2] or "").strip()
        if not name or name in {"测试项目", "ELP测试项目", "ELP / 测试项目"}:
            continue
        plan.test_work_modes[name] = mode.replace(" / ", "\n")


def _parse_function_states(plan: ElpPlan, table: Sequence[Sequence[str]]) -> None:
    rows: List[Tuple[str, str]] = []
    for row in table[1:]:
        if len(row) < 3:
            name, desc = (row[0] if row else ""), (row[1] if len(row) > 1 else "")
        else:
            name, desc = row[1], row[2]
            if not name and row[0].startswith("功能状态"):
                name, desc = row[0], row[1]
        name = (name or "").strip()
        desc = (desc or "").strip()
        if name.startswith("功能状态"):
            rows.append((name, desc))
    if rows:
        plan.function_states = rows


def _table_blob(table) -> str:
    raw = table.extract() or []
    return "".join(str(cell or "") for row in raw[:3] for cell in row)


def _chapter6_image_key(blob: str) -> str:
    text = blob or ""
    if "GEELY" in text:
        return ""
    if "电子电器组件种类" in text:
        return CHAPTER6_BASIC
    if "产品功能分类" in text:
        return CHAPTER6_FUNCTION_CLASS
    if "功能状态" in text and "定义描述" in text:
        return CHAPTER6_STATES
    if "工作模式" in text and "定义描述" in text and "功能状态" not in text:
        return CHAPTER6_WORK_MODES
    if (
        "功能描述" in text
        and "可接受范围" in text
        and "功能项" not in text
        and "监控方式" not in text
    ):
        return CHAPTER6_MONITOR
    return ""


def _is_footer_line(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if compact.startswith("GL."):
        return True
    return "共" in compact and "页" in compact and "测试计划" in compact


def _work_mode_note_bottom(page, table_bottom: float, ceiling: float) -> float:
    """Include the 备注 block that sits under the work-mode table, outside its border."""
    words = [
        word
        for word in (page.extract_words() or [])
        if word["top"] >= table_bottom - 2 and word["top"] < ceiling and word["top"] < page.height - 28
    ]
    if not words:
        return table_bottom
    lines: List[List[dict]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    started = False
    last_bottom = table_bottom
    prev_bottom = table_bottom
    for line in lines:
        text = "".join(word["text"] for word in line)
        top = min(word["top"] for word in line)
        bottom = max(word["bottom"] for word in line)
        if _is_footer_line(text):
            break
        if not started:
            if "备注" in text and top - table_bottom < 40:
                started = True
                last_bottom = bottom
                prev_bottom = bottom
            elif top - table_bottom > 36:
                break
            continue
        if top - prev_bottom > 18:
            break
        if text.startswith("——") or text.startswith("3.") or "见下表" in text:
            break
        last_bottom = bottom
        prev_bottom = bottom
    if not started:
        return table_bottom
    return min(last_bottom + 3, ceiling - 2, page.height - 24)


def _iter_rule_segments(page):
    """Thin strokes pdfplumber stored as rects or lines."""
    for rect in page.rects or []:
        yield rect["x0"], rect["top"], rect["x1"], rect["bottom"]
    for line in page.lines or []:
        yield line["x0"], line["top"], line["x1"], line["bottom"]


def _snap_bbox_to_rules(
    page, bbox: Tuple[float, float, float, float]
) -> Tuple[float, float, float, float]:
    """Grow a detected table box out to ruling lines that sit just outside it.

    pdfplumber's bbox often starts inside the outer border. On the seatbelt
    plan the left rule is about 6pt left of the 6.4 / 6.5 cell box.
    """
    x0, top, x1, bottom = bbox
    slack = _RULE_SNAP_PT
    for rx0, rtop, rx1, rbottom in _iter_rule_segments(page):
        width = rx1 - rx0
        height = rbottom - rtop
        if width < 2.5 and height > 4:
            cx = (rx0 + rx1) / 2
            if rbottom < top - 1 or rtop > bottom + 1:
                continue
            if x0 - slack <= cx <= x0 + 1:
                x0 = min(x0, rx0)
            elif x1 - 1 <= cx <= x1 + slack:
                x1 = max(x1, rx1)
        elif height < 2.5 and width > 4:
            cy = (rtop + rbottom) / 2
            if rx1 < x0 - 1 or rx0 > x1 + 1:
                continue
            if top - slack <= cy <= top + 1:
                top = min(top, rtop)
            elif bottom - 1 <= cy <= bottom + slack:
                bottom = max(bottom, rbottom)
    return x0, top, x1, bottom


def _render_crop_png(page, bbox: Tuple[float, float, float, float]) -> bytes:
    x0, top, x1, bottom = _snap_bbox_to_rules(page, bbox)
    pad = _CROP_PAD_PT
    box = (
        max(0.0, x0 - pad),
        max(0.0, top - pad),
        min(page.width, x1 + pad),
        min(page.height, bottom + pad),
    )
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return b""
    image = page.crop(box).to_image(resolution=_CHAPTER6_IMAGE_DPI)
    buf = io.BytesIO()
    image.original.save(buf, format="PNG")
    return buf.getvalue()


def _collect_chapter6_images(page, shots: Dict[str, bytes]) -> None:
    tables = page.find_tables() or []
    matched = []
    for table in tables:
        key = _chapter6_image_key(_table_blob(table))
        if not key or key in shots:
            continue
        matched.append((table, key))
    for table, key in matched:
        x0, top, x1, bottom = table.bbox
        if key == CHAPTER6_WORK_MODES:
            later = [other.bbox[1] for other in tables if other.bbox[1] > bottom + 2]
            ceiling = min(later) if later else page.height - 20
            bottom = _work_mode_note_bottom(page, bottom, ceiling)
        try:
            png = _render_crop_png(page, (x0, top, x1, bottom))
        except Exception:
            continue
        if png:
            shots[key] = png


def _extract_work_mode_notes(chunks: Sequence[str]) -> str:
    for text in chunks:
        idx = text.find("备注")
        if idx < 0:
            continue
        block = text[idx:]
        end = block.find("3.2")
        if end > 0:
            block = block[:end]
        return block.strip()
    return ""
