"""申请单解析结果模型（仅客户信息 + 样品信息，不含测试信息第 3 页）。"""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class FileSource(BaseModel):
    file_type: str  # "application"
    filename: str


class ApplicationData(BaseModel):
    """从申请单第 1/2 页（或沃尔沃单页）抽出的客户与样品信息。"""

    source: FileSource
    applicant_name: str
    applicant_address: str
    applicant_name_cn: str = ""
    applicant_name_en: str = ""
    applicant_address_cn: str = ""
    applicant_address_en: str = ""
    # 「报告抬头公司/地址（Company shown on report）」；与申请公司不一致时优先用此字段。
    report_title_name_cn: str = ""
    report_title_name_en: str = ""
    report_title_address_cn: str = ""
    report_title_address_en: str = ""
    sample_info: Dict[str, str] = Field(default_factory=dict)
    # 多样品列：同行各组可选值（key → [col1, col2, ...]）
    sample_info_candidates: Dict[str, List[str]] = Field(default_factory=dict)
    # Sheet2 各列样品名称（按 001/002/… 顺序；沃尔沃单页通常为空）
    sample_column_names: List[str] = Field(default_factory=list)
