import base64
import json
import uuid
from enum import Enum
from pathlib import Path
from typing import ClassVar, Dict, Iterator, List, Optional, Tuple
from pydantic import BaseModel, Field, field_serializer, field_validator

from src.sample_columns import ALL_SAMPLE_COLUMNS, merge_sample_column_dicts

class TestResult(str, Enum):
    PASS = "合格"
    FAIL = "不合格"
    NA = "N/A"

class DataTableRef(BaseModel):
    """Index entry for a data-table xlsx under 数据表附件/."""

    title: str
    relative_path: str


class CustomOverviewField(BaseModel):
    """User-added project overview row; label and value are editable per language side."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    label_cn: str = ""
    value_cn: str = ""
    label_en: str = ""
    value_en: str = ""


def _coerce_test_result(value):
    mapping = {
        "Pass": "合格",
        "Fail": "不合格",
        "合格": "合格",
        "不合格": "不合格",
        "N/A": "N/A",
        "NA": "N/A",
    }
    if isinstance(value, TestResult):
        return value
    return mapping.get(str(value), value)


class SampleStandardResult(BaseModel):
    """Per-standard outcome for one sample row (multi-standard tables)."""

    standard_id: str = ""
    chapter: str = ""
    result: TestResult = TestResult.NA
    result_desc: Optional[str] = None

    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, value):
        return _coerce_test_result(value)

    def ref_key(self) -> tuple:
        return (self.standard_id or "", self.chapter or "")


class TestSample(BaseModel):
    sample_id: str
    result: TestResult = TestResult.NA
    result_desc: Optional[str] = None
    notes: Optional[str] = None
    standard_results: List[SampleStandardResult] = Field(default_factory=list)

    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, value):
        return _coerce_test_result(value)

    def result_for(self, std) -> TestResult:
        """Conclusion for a standard; falls back to scalar ``result`` for legacy data."""
        sid = getattr(std, "standard_id", None) or ""
        chap = getattr(std, "chapter", None) or ""
        if isinstance(std, (tuple, list)) and len(std) >= 2:
            sid, chap = std[0] or "", std[1] or ""
        key = (sid, chap)
        for entry in self.standard_results or []:
            if entry.ref_key() == key:
                return entry.result
        return self.result

    def desc_for(self, std) -> Optional[str]:
        sid = getattr(std, "standard_id", None) or ""
        chap = getattr(std, "chapter", None) or ""
        if isinstance(std, (tuple, list)) and len(std) >= 2:
            sid, chap = std[0] or "", std[1] or ""
        key = (sid, chap)
        for entry in self.standard_results or []:
            if entry.ref_key() == key:
                return entry.result_desc
        return self.result_desc

    def all_results(self) -> List[TestResult]:
        """All conclusions used for node-level aggregation."""
        if self.standard_results:
            return [entry.result for entry in self.standard_results]
        return [self.result]

class TestEquipment(BaseModel):
    name: str = ""
    name_en: str = ""
    code: str = ""  # report/UI number, e.g. TTE20236127-V066
    model: str = ""
    valid_date: str = ""  # 校准有效期 yyyy-MM-dd, captured at selection time


class TestStandard(BaseModel):
    """One library row, stored in the order the user checked it."""
    standard_id: str = ""
    chapter: str = ""
    test_name: str = ""
    test_item: str = ""  # library English 「test item」
    standard_desc: str = ""
    standard_desc_en: str = ""
    result_desc: str = ""
    result_desc_en: str = ""
    evaluation_req: str = ""
    evaluation_req_en: str = ""
    env_condition: str = ""  # library 「环境温湿度」
    images: List[bytes] = Field(default_factory=list)
    key_params: List[str] = Field(default_factory=list)
    key_params_defaults: List[str] = Field(default_factory=list)
    key_params_confirmed: bool = False

    @field_serializer("images")
    def _serialize_images(self, value):
        return [base64.b64encode(blob).decode("ascii") for blob in (value or []) if blob]

    @field_validator("images", mode="before")
    @classmethod
    def _parse_images(cls, value):
        if not value:
            return []
        out = []
        for item in value:
            if isinstance(item, bytes):
                if item:
                    out.append(item)
            elif isinstance(item, str) and item.strip():
                out.append(base64.b64decode(item))
        return out

    def ref_key(self) -> tuple:
        """Library lookup key: 标准号 + 章节号, never 试验名称."""
        return (self.standard_id or "", self.chapter or "")

    def identity_key(self) -> tuple:
        return (self.standard_id or "", self.chapter or "", self.test_name or "")

    def label(self) -> str:
        return " / ".join(p for p in (self.standard_id, self.chapter, self.test_name) if p)

    def ref_label(self) -> str:
        return " / ".join(p for p in (self.standard_id, self.chapter) if p)

    def condition_title(self) -> str:
        bits = []
        if self.standard_id:
            bits.append(self.standard_id)
        if self.chapter:
            bits.append(f"章节号 {self.chapter}")
        if self.test_name:
            bits.append(self.test_name)
        return "，".join(bits) or "未命名标准"

    def field_title(self) -> str:
        """Drawer / result-row label: test name only, no repeated 标准号 / 章节号."""
        return self.test_name or self.condition_title()

    def method_block(self) -> str:
        return self.ref_label()

    def needs_key_param_confirm(self) -> bool:
        return bool(self.key_params_defaults) and not self.key_params_confirmed


def _join_blocks(parts) -> str:
    return "\n\n".join(p.strip() for p in parts if p and str(p).strip())


class TestNode(BaseModel):
    test_name: str
    test_name_en: str = ""
    standard_id: Optional[str] = None
    standard_chapter: Optional[str] = None
    standard_test_name: Optional[str] = None
    standard_desc: Optional[str] = None
    standard_desc_en: Optional[str] = None
    result_desc: Optional[str] = None
    result_desc_en: Optional[str] = None
    evaluation_req: Optional[str] = None
    evaluation_req_en: Optional[str] = None
    standards: List[TestStandard] = Field(default_factory=list)
    equipment_name: Optional[str] = None
    equipments: List[TestEquipment] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    env_condition: Optional[str] = None  # test environment; from standard library or user edit
    samples: List[TestSample] = Field(default_factory=list)
    data_tables: List[DataTableRef] = Field(default_factory=list)
    # Manual order of photo album folders under 3.测试组/{Leg名}-{试验名}/; empty → default sort.
    photo_album_order: List[str] = Field(default_factory=list)
    # Selected standards whose sample-result tables were removed (条件等仍保留).
    # Each entry is (标准号, 章节号). Uncheck then re-check restores the table.
    result_table_omissions: List[Tuple[str, str]] = Field(default_factory=list)

    @field_validator("result_table_omissions", mode="before")
    @classmethod
    def _coerce_result_table_omissions(cls, value):
        if not value:
            return []
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(
                    (str(item.get("standard_id") or ""), str(item.get("chapter") or ""))
                )
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                out.append((str(item[0] or ""), str(item[1] or "")))
        return out

    @staticmethod
    def _has_text(value) -> bool:
        return bool(value and str(value).strip())

    def omitted_result_key_set(self) -> set:
        return {(a or "", b or "") for a, b in (self.result_table_omissions or [])}

    def result_table_standards(self) -> List[TestStandard]:
        """Standards that still have a sample-result table (excludes UI omissions)."""
        omitted = self.omitted_result_key_set()
        return [s for s in self.resolved_standards() if s.ref_key() not in omitted]

    def resolved_standards(self) -> List[TestStandard]:
        """Checked standards in selection order; falls back to legacy scalar fields."""
        if self.standards:
            return list(self.standards)
        if any(
            self._has_text(v)
            for v in (
                self.standard_id,
                self.standard_chapter,
                self.standard_test_name,
                self.standard_desc,
                self.standard_desc_en,
                self.result_desc,
                self.result_desc_en,
                self.evaluation_req,
                self.evaluation_req_en,
            )
        ):
            return [
                TestStandard(
                    standard_id=self.standard_id or "",
                    chapter=self.standard_chapter or "",
                    test_name=self.standard_test_name or "",
                    standard_desc=self.standard_desc or "",
                    standard_desc_en=self.standard_desc_en or "",
                    result_desc=self.result_desc or "",
                    result_desc_en=self.result_desc_en or "",
                    evaluation_req=self.evaluation_req or "",
                    evaluation_req_en=self.evaluation_req_en or "",
                )
            ]
        return []

    def joined_test_method(self) -> str:
        return "；".join(s.ref_label() for s in self.resolved_standards() if s.ref_label())

    def joined_standard_desc(self) -> str:
        return _join_blocks(s.standard_desc for s in self.resolved_standards())

    def joined_standard_desc_en(self) -> str:
        return _join_blocks(s.standard_desc_en for s in self.resolved_standards())

    def joined_evaluation_req(self) -> str:
        return _join_blocks(s.evaluation_req for s in self.resolved_standards())

    def joined_evaluation_req_en(self) -> str:
        return _join_blocks(s.evaluation_req_en for s in self.resolved_standards())

    def joined_result_desc_en(self) -> str:
        return _join_blocks(s.result_desc_en for s in self.resolved_standards())

    def joined_test_item(self) -> str:
        return "；".join(s.test_item for s in self.resolved_standards() if (s.test_item or "").strip())

    def card_display_name(self, language: str = "中文") -> str:
        """Leg card / report label for the given language side."""
        lang = (language or "中文").strip()
        if lang == "英文":
            return (self.test_name_en or "").strip()
        return (self.test_name or "").strip()

    def sync_card_names_from_standards(self) -> None:
        """Overwrite card labels from the first selected standard (always on save)."""
        stds = self.resolved_standards()
        if not stds:
            return
        first = stds[0]
        cn = (first.test_name or "").strip()
        if cn:
            self.test_name = cn
        self.test_name_en = (first.test_item or "").strip()

    def resolved_env_condition(self) -> str:
        if self._has_text(self.env_condition):
            return str(self.env_condition).strip()
        for std in self.resolved_standards():
            if self._has_text(std.env_condition):
                return str(std.env_condition).strip()
        return ""

    def apply_standards(self, picked: List[TestStandard]) -> None:
        """Persist selection order. Concatenate method/conditions/eval; never smash result_desc."""
        self.standards = list(picked or [])
        if not self.standards:
            self.standard_id = None
            self.standard_chapter = None
            self.standard_test_name = None
            self.standard_desc = None
            self.standard_desc_en = None
            self.result_desc = None
            self.result_desc_en = None
            self.evaluation_req = None
            self.evaluation_req_en = None
            return
        self.standard_id = _join_blocks(s.standard_id for s in self.standards) or None
        self.standard_chapter = _join_blocks(s.chapter for s in self.standards) or None
        self.standard_test_name = _join_blocks(s.test_name for s in self.standards) or None
        self.standard_desc = self.joined_standard_desc() or None
        self.standard_desc_en = self.joined_standard_desc_en() or None
        self.evaluation_req = self.joined_evaluation_req() or None
        self.evaluation_req_en = self.joined_evaluation_req_en() or None
        if len(self.standards) == 1:
            self.result_desc = self.standards[0].result_desc or None
            self.result_desc_en = self.standards[0].result_desc_en or None
        else:
            self.result_desc = None
            self.result_desc_en = None

    def is_detail_complete(self) -> bool:
        """True when standard, key params, equipment, and sample results are filled."""
        has_standard = bool(self.resolved_standards()) or any(
            self._has_text(v)
            for v in (self.standard_id, self.standard_chapter, self.standard_test_name)
        )
        has_equipment = self._has_text(self.equipment_name) or any(
            self._has_text(eq.name) or self._has_text(eq.code)
            for eq in (self.equipments or [])
        )
        has_results = any(self._has_text(s.sample_id) for s in (self.samples or []))
        params_ok = all(not s.needs_key_param_confirm() for s in self.resolved_standards())
        return has_standard and has_equipment and has_results and params_ok
    
class TestLeg(BaseModel):
    leg_id: str
    leg_name: str
    nodes: List[TestNode] = Field(default_factory=list)


DUPLICATE_TEST_NAME_MESSAGE = "同一 Leg 内试验名称重复，请确认"

_USABLE_TEST_NAME_BLOCKLIST = {"请选择试验...", "自定义"}


def _usable_test_name(name: str) -> bool:
    text = (name or "").strip()
    return bool(text) and text not in _USABLE_TEST_NAME_BLOCKLIST


class ProjectState(BaseModel):
    project_id: str = ""
    source_path: str = ""
    project_path: str = ""
    # 编辑语言：中文 | 英文（与导出语言独立）
    edit_language: str = "中文"
    applicant_name: str = ""
    applicant_address: str = ""
    applicant_name_en: str = ""
    applicant_address_en: str = ""
    report_title_name: str = ""
    report_title_address: str = ""
    report_title_name_en: str = ""
    report_title_address_en: str = ""
    sample_name: str = ""
    sample_name_en: str = ""
    sample_receive_date: str = ""
    test_start_date: str = ""
    test_end_date: str = ""
    # 申请单首页全部字段（含主机厂、生产商等）
    application_fields: Dict[str, str] = Field(default_factory=dict)
    application_fields_en: Dict[str, str] = Field(default_factory=dict)
    # 申请单样品信息页多列（001/002…）；active=-1 表示 All 合并视图
    application_columns: List[Dict[str, str]] = Field(default_factory=list)
    application_columns_en: List[Dict[str, str]] = Field(default_factory=list)
    sample_column_tab_labels: List[str] = Field(default_factory=list)
    active_sample_column_index: int = 0
    # 用户从项目概况中移除的字段，不再写入报告
    excluded_overview_keys: List[str] = Field(default_factory=list)
    # 用户手动添加的项目信息行（标题与内容均可编辑）
    custom_overview_fields: List[CustomOverviewField] = Field(default_factory=list)
    
    candidate_pool: List[str] = Field(default_factory=list)
    template_pool: List[str] = Field(default_factory=list)
    last_leg_template_name: str = ""
    legs: List[TestLeg] = Field(default_factory=list)

    def iter_nodes_for_export(self, leg_filter: Optional[str] = None) -> Iterator[Tuple["TestLeg", TestNode]]:
        """Same scope rules as WordGenerator.generate."""
        if not leg_filter or leg_filter == "ALL":
            for leg in self.legs or []:
                for node in leg.nodes or []:
                    yield leg, node
            return
        if str(leg_filter).startswith("TEST:"):
            test_target = str(leg_filter).replace("TEST:", "", 1)
            for leg in self.legs or []:
                for node in leg.nodes or []:
                    if f"{leg.leg_name} - {node.test_name}" == test_target:
                        yield leg, node
                        return
            return
        for leg in self.legs or []:
            if leg.leg_id == leg_filter:
                for node in leg.nodes or []:
                    yield leg, node
                return

    def incomplete_export_labels(self, leg_filter: Optional[str] = None) -> List[str]:
        labels = []
        for leg, node in self.iter_nodes_for_export(leg_filter):
            if node.is_detail_complete():
                continue
            name = (node.test_name or "").strip() or "（未命名试验）"
            labels.append(f"{leg.leg_name} / {name}")
        return labels

    def duplicate_test_names(self) -> List[str]:
        """Usable test names that appear more than once within any single Leg."""
        dupes: set[str] = set()
        for leg in self.legs or []:
            counts: Dict[str, int] = {}
            for node in leg.nodes or []:
                name = (node.test_name or "").strip()
                if not _usable_test_name(name):
                    continue
                counts[name] = counts.get(name, 0) + 1
            dupes.update(name for name, count in counts.items() if count > 1)
        return sorted(dupes)

    def test_name_usage_count_in_leg(self, leg_id: str, test_name: str) -> int:
        needle = (test_name or "").strip()
        if not needle:
            return 0
        count = 0
        for leg in self.legs or []:
            if leg.leg_id != leg_id:
                continue
            for node in leg.nodes or []:
                if (node.test_name or "").strip() == needle:
                    count += 1
        return count

    def test_name_is_unique_in_leg(self, leg_id: str, test_name: str) -> bool:
        return self.test_name_usage_count_in_leg(leg_id, test_name) <= 1

    def test_name_usage_count(self, test_name: str) -> int:
        needle = (test_name or "").strip()
        if not needle:
            return 0
        count = 0
        for leg in self.legs or []:
            for node in leg.nodes or []:
                if (node.test_name or "").strip() == needle:
                    count += 1
        return count

    def test_name_is_unique(self, test_name: str) -> bool:
        """Deprecated for hook/save checks — prefer test_name_is_unique_in_leg."""
        return self.test_name_usage_count(test_name) <= 1

    def combo_pool(self, extra: str = "") -> List[str]:
        """Dropdown items: quotation pool then template pool, exact-string unique."""
        seen = set()
        out: List[str] = []
        for name in list(self.candidate_pool or []) + list(self.template_pool or []):
            text = (name or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        extra_text = (extra or "").strip()
        if extra_text and extra_text not in seen:
            out.append(extra_text)
        return out
    
    def migrate_legacy_card_names(self) -> None:
        """Backfill test_name_en from standards when loading older project files."""
        for leg in self.legs or []:
            for node in leg.nodes or []:
                if (node.test_name_en or "").strip():
                    continue
                fallback = node.joined_test_item()
                if fallback:
                    node.test_name_en = fallback

    @classmethod
    def load_from_file(cls, filepath: str) -> "ProjectState":
        path = Path(filepath)
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            state = cls(**data)
            state.migrate_legacy_card_names()
            return state
            
    def save_to_file(self, filepath: str):
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    CUSTOM_OVERVIEW_PREFIX: ClassVar[str] = "@custom:"

    _OVERVIEW_HEAD: ClassVar[tuple] = (
        "申请单号",
        "申请公司",
        "申请公司地址",
        "报告抬头公司",
        "报告抬头地址",
        "样品名称",
    )
    _OVERVIEW_ATTR: ClassVar[Dict[str, str]] = {
        "申请公司": "applicant_name",
        "申请公司地址": "applicant_address",
        "报告抬头公司": "report_title_name",
        "报告抬头地址": "report_title_address",
        "样品名称": "sample_name",
    }
    _OVERVIEW_ATTR_EN: ClassVar[Dict[str, str]] = {
        "申请公司": "applicant_name_en",
        "申请公司地址": "applicant_address_en",
        "报告抬头公司": "report_title_name_en",
        "报告抬头地址": "report_title_address_en",
        "样品名称": "sample_name_en",
    }

    def _edit_lang(self) -> str:
        lang = (self.edit_language or "中文").strip()
        return "英文" if lang == "英文" else "中文"

    @classmethod
    def is_custom_overview_key(cls, key: str) -> bool:
        return (key or "").startswith(cls.CUSTOM_OVERVIEW_PREFIX)

    @classmethod
    def custom_overview_key(cls, field_id: str) -> str:
        return f"{cls.CUSTOM_OVERVIEW_PREFIX}{field_id}"

    def parse_custom_overview_id(self, key: str) -> Optional[str]:
        if not self.is_custom_overview_key(key):
            return None
        return key[len(self.CUSTOM_OVERVIEW_PREFIX) :]

    def _custom_overview_row(self, field_id: str) -> Optional[CustomOverviewField]:
        needle = (field_id or "").strip()
        if not needle:
            return None
        for row in self.custom_overview_fields or []:
            if row.id == needle:
                return row
        return None

    def overview_display_label(self, key: str, language: Optional[str] = None) -> str:
        from src.language_copy import field_label

        lang = (language or self._edit_lang()).strip()
        if lang != "英文":
            lang = "中文"
        if self.is_custom_overview_key(key):
            row = self._custom_overview_row(self.parse_custom_overview_id(key) or "")
            if not row:
                return ""
            if lang == "英文":
                return (row.label_en or row.label_cn or "").strip()
            return (row.label_cn or row.label_en or "").strip()
        return field_label(key, lang) or key

    def add_custom_overview_field(self) -> CustomOverviewField:
        row = CustomOverviewField()
        fields = list(self.custom_overview_fields or [])
        fields.append(row)
        self.custom_overview_fields = fields
        return row

    def set_custom_overview_label(self, field_id: str, label: str) -> None:
        row = self._custom_overview_row(field_id)
        if not row:
            return
        label = (label or "").strip()
        if self._edit_lang() == "英文":
            row.label_en = label
        else:
            row.label_cn = label

    def set_custom_overview_value(self, field_id: str, value: str) -> None:
        row = self._custom_overview_row(field_id)
        if not row:
            return
        value = (value or "").strip()
        if self._edit_lang() == "英文":
            row.value_en = value
        else:
            row.value_cn = value

    def remove_custom_overview_field(self, field_id: str) -> None:
        needle = (field_id or "").strip()
        if not needle:
            return
        self.custom_overview_fields = [
            row for row in (self.custom_overview_fields or []) if row.id != needle
        ]
        key = self.custom_overview_key(needle)
        excluded = list(self.excluded_overview_keys or [])
        if key in excluded:
            self.excluded_overview_keys = [k for k in excluded if k != key]

    def has_multiple_sample_columns(self) -> bool:
        return len(self.application_columns or []) > 1

    def is_all_sample_columns_active(self) -> bool:
        return (
            self.has_multiple_sample_columns()
            and self.active_sample_column_index == ALL_SAMPLE_COLUMNS
        )

    def _sample_column_field_map(self, language: Optional[str] = None) -> Dict[str, str]:
        lang = (language or self._edit_lang()).strip()
        columns = self.application_columns or []
        columns_en = self.application_columns_en or []
        if not columns:
            return {}
        if self.is_all_sample_columns_active():
            if lang == "英文":
                return merge_sample_column_dicts(columns_en)
            return merge_sample_column_dicts(columns)
        idx = self.active_sample_column_index
        if idx < 0 or idx >= len(columns):
            idx = 0
        if lang == "英文":
            return dict(columns_en[idx] if idx < len(columns_en) else {})
        return dict(columns[idx])

    def sync_application_fields_from_sample_column(self) -> None:
        """Project overview + export read application_fields; sync from active column."""
        from src.language_copy import english_from_application

        cn = self._sample_column_field_map("中文")
        en = self._sample_column_field_map("英文")
        self.application_fields = cn
        self.application_fields_en = en
        self.sample_name = cn.get("样品名称", "") or self.sample_name
        explicit_en = en.get("样品名称", "")
        self.sample_name_en = explicit_en or english_from_application(
            self.sample_name, self.sample_name_en or ""
        )

    def set_active_sample_column(self, index: int) -> None:
        if not self.has_multiple_sample_columns():
            self.active_sample_column_index = 0
            return
        if index == ALL_SAMPLE_COLUMNS:
            self.active_sample_column_index = ALL_SAMPLE_COLUMNS
        elif 0 <= index < len(self.application_columns):
            self.active_sample_column_index = index
        self.sync_application_fields_from_sample_column()

    def overview_field_map(self, language: Optional[str] = None) -> Dict[str, str]:
        lang = (language or self._edit_lang()).strip()
        if lang == "英文":
            fields = dict(self.application_fields_en or {})
            for key, attr in self._OVERVIEW_ATTR_EN.items():
                val = (getattr(self, attr, None) or "").strip()
                if val:
                    fields[key] = val
            return fields
        fields = dict(self.application_fields or {})
        for key, attr in self._OVERVIEW_ATTR.items():
            val = (getattr(self, attr, None) or "").strip()
            if val:
                fields[key] = val
        return fields

    def iter_overview_fields(self, language: Optional[str] = None):
        """Visible homepage fields. Skips user-removed keys.

        When language is omitted, uses edit_language. English mode yields a row when
        the Chinese side has a value (EN may be empty).
        """
        excluded = set(self.excluded_overview_keys or [])
        lang = (language or self._edit_lang()).strip()
        if lang != "英文":
            lang = "中文"
        cn_fields = self.overview_field_map("中文")
        show_fields = self.overview_field_map(lang)
        keys: List[str] = []
        seen = set()
        for key in self._OVERVIEW_HEAD:
            seen.add(key)
            keys.append(key)
        for key in cn_fields.keys():
            if key not in seen:
                seen.add(key)
                keys.append(key)
        if lang == "英文":
            for key in show_fields.keys():
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        for key in keys:
            if key in excluded:
                continue
            cn_val = (cn_fields.get(key) or "").strip()
            val = (show_fields.get(key) or "").strip()
            if lang == "英文":
                if cn_val or val:
                    yield key, val
            elif val:
                yield key, val
        for row in self.custom_overview_fields or []:
            key = self.custom_overview_key(row.id)
            if key in excluded:
                continue
            cn_label = (row.label_cn or "").strip()
            cn_val = (row.value_cn or "").strip()
            en_label = (row.label_en or "").strip()
            en_val = (row.value_en or "").strip()
            if lang == "英文":
                if not (cn_label or cn_val or en_label or en_val):
                    continue
                yield key, en_val
            elif cn_label or cn_val or en_label or en_val:
                yield key, cn_val

    def set_overview_value(self, key: str, value: str) -> None:
        """Write one overview field into the side matching edit_language."""
        key = (key or "").strip()
        value = (value or "").strip()
        if not key:
            return
        if self.is_custom_overview_key(key):
            field_id = self.parse_custom_overview_id(key)
            if field_id:
                self.set_custom_overview_value(field_id, value)
            return
        if self._edit_lang() == "英文":
            attr = self._OVERVIEW_ATTR_EN.get(key)
            if attr:
                setattr(self, attr, value)
            fields = dict(self.application_fields_en or {})
            if value:
                fields[key] = value
            else:
                fields.pop(key, None)
            self.application_fields_en = fields
            self._write_active_sample_column_field(key, value, english=True)
            return
        attr = self._OVERVIEW_ATTR.get(key)
        if attr:
            setattr(self, attr, value)
        fields = dict(self.application_fields or {})
        if value:
            fields[key] = value
        else:
            fields.pop(key, None)
        self.application_fields = fields
        self._write_active_sample_column_field(key, value, english=False)

    def _write_active_sample_column_field(
        self, key: str, value: str, *, english: bool
    ) -> None:
        if self.is_all_sample_columns_active():
            return
        idx = self.active_sample_column_index
        columns = list(self.application_columns_en if english else self.application_columns)
        if idx < 0 or idx >= len(columns):
            return
        col = dict(columns[idx])
        if value:
            col[key] = value
        else:
            col.pop(key, None)
        columns[idx] = col
        if english:
            self.application_columns_en = columns
        else:
            self.application_columns = columns
