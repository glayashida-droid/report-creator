import json
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class TestResult(str, Enum):
    PASS = "Pass"
    FAIL = "Fail"
    NA = "N/A"

class TestSample(BaseModel):
    sample_id: str
    result: TestResult = TestResult.NA
    notes: Optional[str] = None

class TestNode(BaseModel):
    test_name: str
    standard_id: Optional[str] = None
    standard_desc: Optional[str] = None
    evaluation_req: Optional[str] = None
    equipment_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    samples: List[TestSample] = Field(default_factory=list)
    
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
