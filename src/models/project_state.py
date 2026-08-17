import base64
import json
from enum import Enum
from pathlib import Path
from typing import ClassVar, Dict, Iterator, List, Optional, Tuple
from pydantic import BaseModel, Field, field_serializer, field_validator

class TestResult(str, Enum):
    PASS = "合格"
    FAIL = "不合格"
    NA = "N/A"

class TestSample(BaseModel):
    sample_id: str
    result: TestResult = TestResult.NA
    result_desc: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("result", mode="before")
    @classmethod
    def _coerce_result(cls, value):
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

class TestEquipment(BaseModel):
    name: str = ""
    code: str = ""
    model: str = ""


class TestStandard(BaseModel):
    """One library row, stored in the order the user checked it."""
    standard_id: str = ""
    chapter: str = ""
    test_name: str = ""
    standard_desc: str = ""
    result_desc: str = ""
    evaluation_req: str = ""
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
    standard_id: Optional[str] = None
    standard_chapter: Optional[str] = None
    standard_test_name: Optional[str] = None
    standard_desc: Optional[str] = None
    result_desc: Optional[str] = None
    evaluation_req: Optional[str] = None
    standards: List[TestStandard] = Field(default_factory=list)
    equipment_name: Optional[str] = None
    equipments: List[TestEquipment] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    samples: List[TestSample] = Field(default_factory=list)

    @staticmethod
    def _has_text(value) -> bool:
        return bool(value and str(value).strip())

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
                self.result_desc,
                self.evaluation_req,
            )
        ):
            return [
                TestStandard(
                    standard_id=self.standard_id or "",
                    chapter=self.standard_chapter or "",
                    test_name=self.standard_test_name or "",
                    standard_desc=self.standard_desc or "",
                    result_desc=self.result_desc or "",
                    evaluation_req=self.evaluation_req or "",
                )
            ]
        return []

    def joined_test_method(self) -> str:
        return "；".join(s.ref_label() for s in self.resolved_standards() if s.ref_label())

    def joined_standard_desc(self) -> str:
        return _join_blocks(s.standard_desc for s in self.resolved_standards())

    def joined_evaluation_req(self) -> str:
        return _join_blocks(s.evaluation_req for s in self.resolved_standards())

    def apply_standards(self, picked: List[TestStandard]) -> None:
        """Persist selection order. Concatenate method/conditions/eval; never smash result_desc."""
        self.standards = list(picked or [])
        if not self.standards:
            self.standard_id = None
            self.standard_chapter = None
            self.standard_test_name = None
            self.standard_desc = None
            self.result_desc = None
            self.evaluation_req = None
            return
        self.standard_id = _join_blocks(s.standard_id for s in self.standards) or None
        self.standard_chapter = _join_blocks(s.chapter for s in self.standards) or None
        self.standard_test_name = _join_blocks(s.test_name for s in self.standards) or None
        self.standard_desc = self.joined_standard_desc() or None
        self.evaluation_req = self.joined_evaluation_req() or None
        if len(self.standards) == 1:
            self.result_desc = self.standards[0].result_desc or None
        else:
            self.result_desc = None

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

class ProjectState(BaseModel):
    project_id: str = ""
    source_path: str = ""
    project_path: str = ""
    applicant_name: str = ""
    applicant_address: str = ""
    report_title_name: str = ""
    report_title_address: str = ""
    sample_name: str = ""
    sample_receive_date: str = ""
    test_start_date: str = ""
    test_end_date: str = ""
    # 申请单首页全部字段（含主机厂、生产商等）
    application_fields: Dict[str, str] = Field(default_factory=dict)
    # 用户从项目概况中移除的字段，不再写入报告
    excluded_overview_keys: List[str] = Field(default_factory=list)
    
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
    
    @classmethod
    def load_from_file(cls, filepath: str) -> "ProjectState":
        path = Path(filepath)
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return cls(**data)
            
    def save_to_file(self, filepath: str):
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

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

    def overview_field_map(self) -> Dict[str, str]:
        fields = dict(self.application_fields or {})
        for key, attr in self._OVERVIEW_ATTR.items():
            val = (getattr(self, attr, None) or "").strip()
            if val:
                fields[key] = val
        return fields

    def iter_overview_fields(self):
        """Visible homepage fields, 申请单号 first. Skips user-removed keys."""
        excluded = set(self.excluded_overview_keys or [])
        fields = self.overview_field_map()
        seen = set()
        for key in self._OVERVIEW_HEAD:
            seen.add(key)
            if key in excluded:
                continue
            val = (fields.get(key) or "").strip()
            if val:
                yield key, val
        for key, val in fields.items():
            if key in seen or key in excluded:
                continue
            val = (val or "").strip()
            if val:
                yield key, val
