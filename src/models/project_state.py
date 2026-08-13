import json
from enum import Enum
from pathlib import Path
from typing import ClassVar, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

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

class TestNode(BaseModel):
    test_name: str
    standard_id: Optional[str] = None
    standard_chapter: Optional[str] = None
    standard_test_name: Optional[str] = None
    standard_desc: Optional[str] = None
    result_desc: Optional[str] = None
    evaluation_req: Optional[str] = None
    equipment_name: Optional[str] = None
    equipments: List[TestEquipment] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    samples: List[TestSample] = Field(default_factory=list)

    @staticmethod
    def _has_text(value) -> bool:
        return bool(value and str(value).strip())

    def is_detail_complete(self) -> bool:
        """True when standard, equipment, and sample results are all filled."""
        has_standard = any(
            self._has_text(v)
            for v in (self.standard_id, self.standard_chapter, self.standard_test_name)
        )
        has_equipment = self._has_text(self.equipment_name) or any(
            self._has_text(eq.name) or self._has_text(eq.code)
            for eq in (self.equipments or [])
        )
        has_results = any(self._has_text(s.sample_id) for s in (self.samples or []))
        return has_standard and has_equipment and has_results
    
class TestLeg(BaseModel):
    leg_id: str
    leg_name: str
    nodes: List[TestNode] = Field(default_factory=list)

class ProjectState(BaseModel):
    project_id: str = ""
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
    legs: List[TestLeg] = Field(default_factory=list)
    
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
            json.dump(self.model_dump(), f, ensure_ascii=False, indent=2)

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
