"""标签清洗、试验项归一、汇总表↔明细定位、大纲匹配键。"""

import re
from typing import Dict, List, Optional, Tuple

# Application sheet keys are short Chinese labels like 样品名称、申请单号
_LABEL_RE = re.compile(
    r"^([\u4e00-\u9fff]+(?:名称|号|状态|特性|车型|地址|单位|方|序号)*)(?:[/／][\u4e00-\u9fff]+)*"
)
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_ENGLISH_ROW_MARKERS = ("★", "applicant name", "applicant address", "customer", "address shown")


def dedupe_merged_cells(cells: List[str]) -> List[str]:
    """Word merged cells repeat the same text in adjacent columns."""
    result: List[str] = []
    for raw in cells:
        text = raw.strip()
        if not text:
            continue
        if result and result[-1] == text:
            continue
        result.append(text)
    return result


def _collapse_label_spaces(text: str) -> str:
    """地    址 / 委 托 方 -> 地址 / 委托方"""
    return re.sub(r"\s+", "", (text or "").strip())


_PURPOSE_FIELD_KEYS = frozenset({"实验目的", "试验目的", "检测目的"})
_PART_NUMBER_FIELD_KEYS = frozenset({"零件号", "零部件号"})


def normalize_sample_field_key(text: str) -> str:
    """申请单常用「★零件号」前缀；报告常用「样品零件号」。比对前统一剥星号并 clean_label。"""
    raw = (text or "").strip().strip("：: |")
    raw = re.sub(r"^[★☆*]+\s*", "", raw)
    compact = _collapse_label_spaces(raw)
    # 「材料牌号」在模板里常写成「材料/牌号」「基材材质牌号」等，统一到同一键。
    if "牌号" in compact and any(token in compact for token in ("材料", "材质", "基材")):
        return "材料牌号"
    key = clean_label(raw) or raw
    # 申请单「★实验目的」、报告首页「试验目的」「检测目的」混用，比对时统一口径
    if key in _PURPOSE_FIELD_KEYS:
        return "实验目的"
    # 申请单「★零部件号」、报告首页「样品零件号」与「零件号」同义
    if key in _PART_NUMBER_FIELD_KEYS:
        return "零件号"
    return key


def clean_label(text: str) -> str:
    text = (text or "").strip().strip("：: |")
    text = re.sub(r"^[★☆*]+\s*", "", text)
    if not text:
        return ""
    collapsed = _collapse_label_spaces(text)
    match = _LABEL_RE.match(collapsed)
    if match:
        return match.group(0).rstrip("：: ")
    if collapsed and _CHINESE_RE.search(collapsed):
        if collapsed in ("地址", "名称") or collapsed.endswith("地址"):
            return "地址" if "地址" in collapsed else collapsed
    # Drop English tail: "样品名称 Sample Name" / "样品状态State" -> Chinese label
    parts = re.split(r"\s*[A-Za-z]", text, maxsplit=1)
    chinese = parts[0].strip("：: |")
    if chinese and _CHINESE_RE.search(chinese):
        return chinese
    return text.split("|")[0].strip("：: ")


def extract_chinese_text(text: str) -> str:
    """Prefer Chinese segment from bilingual value like '成品Finished products'."""
    text = (text or "").strip()
    if not text:
        return ""
    chunks = _CHINESE_RE.findall(text)
    if chunks:
        return "".join(chunks)
    return text


def normalize_test_item_name(text: str) -> str:
    """Normalize test item titles for matching summary <-> detail/outline.

    保留中英混排原文中的字母（如 A组/Group A），避免各组塌成同一「组」；
    去空白、去括号段、实验→试验，再 casefold 便于英文大小写无关比对。
    纯中文短名仍可通过 ``test_item_titles_match`` 的子串规则命中更长双语标题。
    """
    core = (text or "").strip()
    if not core:
        return ""
    core = re.sub(r"\s+", "", core)
    core = re.sub(r"[（(].*?[）)]", "", core)
    # 大纲常用「实验」、报告常用「试验」
    core = core.replace("实验", "试验")
    return core.casefold().strip()


def test_item_titles_match(summary_title: str, detail_title: str) -> bool:
    """汇总表检测项目名与试验明细标题是否指向同一试验项。"""
    key = normalize_test_item_name(summary_title)
    dkey = normalize_test_item_name(detail_title)
    if not key:
        return False
    if key == dkey:
        return True
    if key in dkey or dkey in key:
        return True
    # 英文标题：忽略大小写与尾部版本号差异
    if not _CHINESE_RE.search(summary_title + detail_title):
        a = re.sub(r"\s+", " ", (summary_title or "").strip()).lower()
        b = re.sub(r"\s+", " ", (detail_title or "").strip()).lower()
        if a and b and (a == b or a in b or b in a):
            return True
    return False


def _matching_title_occurrence(
    titles: List[str], index: int, *, match_fn=test_item_titles_match
) -> int:
    """在 titles[0..index] 中，与 titles[index] 同类的第几次出现（从 1 起）。"""
    if index < 0 or index >= len(titles):
        return 0
    target = titles[index]
    count = 0
    for i in range(index + 1):
        if match_fn(titles[i], target):
            count += 1
    return count


def find_test_detail_index_for_summary(
    summary_items: List[dict],
    test_details: List,
    summary_index: int,
) -> Optional[int]:
    """按汇总表行序 + 重复标题出现次序，定位对应试验明细下标。

    常规报告：汇总表自上而下与试验明细章节一一对应；同名试验（如多段「目视检查」）
    用「第 n 次出现的标题」对齐第 n 个同名明细节。
    """
    summaries = summary_items or []
    details = test_details or []
    if summary_index < 0 or summary_index >= len(summaries):
        return None
    test_item = (summaries[summary_index].get("item") or "").strip()
    if not test_item:
        return None

    sum_titles = [(it.get("item") or "").strip() for it in summaries]
    det_titles = [(getattr(d, "title", "") or "").strip() for d in details]
    title_count = sum(
        1 for t in sum_titles if test_item_titles_match(test_item, t)
    )
    if title_count == 1 and summary_index < len(details):
        if test_item_titles_match(test_item, details[summary_index].title):
            return summary_index

    target_occ = _matching_title_occurrence(sum_titles, summary_index)
    seen = 0
    for di, title in enumerate(det_titles):
        if test_item_titles_match(test_item, title):
            seen += 1
            if seen == target_occ:
                return di
    return None


def find_summary_index_for_detail(
    summary_items: List[dict],
    test_details: List,
    detail_index: int,
) -> Optional[int]:
    """试验明细 → 汇总表行的反向定位（策略与 find_test_detail_index_for_summary 对称）。"""
    summaries = summary_items or []
    details = test_details or []
    if detail_index < 0 or detail_index >= len(details):
        return None
    detail_title = (details[detail_index].title or "").strip()
    if not detail_title:
        return None

    sum_titles = [(it.get("item") or "").strip() for it in summaries]
    det_titles = [(getattr(d, "title", "") or "").strip() for d in details]
    title_count = sum(
        1 for t in det_titles if test_item_titles_match(t, detail_title)
    )
    if title_count == 1 and detail_index < len(summaries):
        si = (summaries[detail_index].get("item") or "").strip()
        if test_item_titles_match(si, detail_title):
            return detail_index

    target_occ = _matching_title_occurrence(det_titles, detail_index)
    seen = 0
    for si, title in enumerate(sum_titles):
        if test_item_titles_match(title, detail_title):
            seen += 1
            if seen == target_occ:
                return si
    return None


_POINT_FUNC_ITEM_RE = re.compile(
    r"(五点|5点|５点|九点|9点|９点)功能",
    re.IGNORECASE,
)


def strict_reference_item_key(text: str) -> str:
    """报价单等严格比对：去空白/括号、实验→试验，再去尾部「试验」后精确相等。"""
    core = normalize_test_item_name(text)
    if not core:
        return ""
    if core.endswith("试验"):
        core = core[:-2]
    return core


def outline_match_key(text: str) -> str:
    """大纲/汇总表检测项目模糊匹配键。

    五点（9点）功能类试验常分「试验前/试验后」，与大纲「五点功能检查」应视为同一项；
    阿拉伯数字 5/9 与中文五点/九点等价。
    """
    compact = re.sub(r"\s+", "", (text or ""))
    compact = re.sub(r"[（(].*?[）)]", "", compact)
    compact = compact.replace("实验", "试验")
    core = normalize_test_item_name(text) or compact
    m = _POINT_FUNC_ITEM_RE.search(compact) or _POINT_FUNC_ITEM_RE.search(core)
    if not m:
        return core
    prefix = m.group(1)
    if prefix in ("5点", "５点", "5"):
        return "五点功能"
    if prefix in ("9点", "９点", "9"):
        return "九点功能"
    return f"{prefix}功能"


# 标准号抽取：企业标 Q/JLY J7110192F-2024、国标 GB/T 250 / GB 11186.2，
# 以及 ISO/IEC/SAE/ASTM/EN/JIS/DIN/VW/GMW/TL/PV/VDA/QC/T/GJB 等常见前缀。
# 用于「检测标准比对」——从一整段检测方法/评价标准文字里剥出标准号，
# 避开章节号(4.1.3)、表号(表2)、温度(-40)、时长(336h) 等噪声。
_DISPIMG_RE = re.compile(r"=?DISPIMG\([^)]*\)", re.IGNORECASE)
_STANDARD_CODE_RE = re.compile(
    r"(?:GB/T|GB|GJB|QC/T|Q/[0-9A-Z]{2,6}|ISO|IEC|SAE|ASTM|EN|JIS|DIN|VW|GMW|TL|PV|VDA)"
    r"\s*[A-Z]?\d[\dA-Za-z.\-]*"
    r"|(?:JA|CA)\s+\d{4}[\w.\-]*(?:-(?:19|20)\d{2})?"
    r"|[A-Z]\d{4,}[A-Za-z]?(?:-(?:19|20)\d{2})?",
    re.IGNORECASE,
)


def _canonical_standard_code(raw: str) -> str:
    """归一到核心码，使「Q/JLY J7110192F-2024」与裸「J7110192F-2024」视为同一标准。"""
    compact = re.sub(r"\s+", "", raw or "").upper()
    m = re.search(r"(?:JA|CA)\d{4}[\w.\-]*(?:-(?:19|20)\d{2})?", compact)
    if m:
        return m.group(0)
    m = re.search(r"[A-Z]\d{4,}[A-Z]?(?:-(?:19|20)\d{2})?", compact)
    return m.group(0) if m else compact


# 标准号后常见脚注/圈码（表达一致性要比对字面，故抽取时一并纳入 surface）。
_STANDARD_TRAILING_MARK_RE = re.compile(r"(?:[①-⑳⑴-⒇]|[*∗※†‡]|\[\d+\])+")


def extract_standard_codes(text: str) -> set:
    """从检测方法/标准文本抽取标准号集合。

    例：「依据Q/JLY J7110192F-2024 第4.1.3和4.2.2章节 表2以及客户要求」→ {'J7110192F-2024'}。
    DISPIMG 图片公式、纯条件（-40℃，6h）不含标准号，返回空集。
    """
    cleaned = _DISPIMG_RE.sub(" ", text or "")
    codes: set = set()
    for m in _STANDARD_CODE_RE.finditer(cleaned):
        code = _canonical_standard_code(m.group(0))
        if code:
            codes.add(code)
    return codes


def extract_standard_surface_forms(text: str) -> list:
    """抽取标准号「字面」写法（保留空格，并吞掉紧随的①等脚注标记）。

    用于报告内表达一致性：同一标准若出现「Q/JLYJ…」与「Q/JLY J…①」应判不一致。
    与 extract_standard_codes 不同，此处不去空白、不剥前缀。
    """
    cleaned = _DISPIMG_RE.sub(" ", text or "")
    surfaces: list = []
    for m in _STANDARD_CODE_RE.finditer(cleaned):
        end = m.end()
        mark = _STANDARD_TRAILING_MARK_RE.match(cleaned, end)
        if mark:
            end = mark.end()
        surface = cleaned[m.start() : end].strip()
        if surface:
            surfaces.append(surface)
    return surfaces


def standard_format_key(surface: str) -> str:
    """去掉空白与脚注标记后的分组键；键相同才比较字面是否一致。"""
    compact = _STANDARD_TRAILING_MARK_RE.sub("", surface or "")
    return re.sub(r"\s+", "", compact).upper()


def conflicting_standard_surface_groups(surfaces) -> list:
    """按 format_key 分组；仅当同一键下出现 ≥2 种字面时返回冲突组。

    不同标准（键不同）、全称 vs 裸号（Q/JLY J711… vs J711…）不会互相比对，避免误报。
    """
    groups: dict = {}
    for raw in surfaces or []:
        surface = (raw or "").strip()
        if not surface:
            continue
        key = standard_format_key(surface)
        if not key:
            continue
        bucket = groups.setdefault(key, [])
        if surface not in bucket:
            bucket.append(surface)
    return [variants for variants in groups.values() if len(variants) > 1]


def pick_by_report_language(cn_value: str, en_value: str, report_value: str) -> str:
    """报告为中文则取申请单中文行，报告为英文则取英文行。"""
    report_value = (report_value or "").strip()
    cn_value = (cn_value or "").strip()
    en_value = (en_value or "").strip()
    if _CHINESE_RE.search(report_value):
        return cn_value or en_value
    if report_value and not _CHINESE_RE.search(report_value):
        return en_value or cn_value
    return cn_value or en_value
