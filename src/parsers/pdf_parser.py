import re
from typing import List

import pdfplumber

_HEADER_MARKERS = ("服务项目", "项目名称", "测试项目")
_CONTENT_MARKERS = ("报价单号", "Quotation No", "Q/CTI QP-VBD")
_SKIP_EXACT = {
    "序号",
    "单位",
    "数量",
    "单价",
    "总价",
    "备注",
    *_HEADER_MARKERS,
}


class QuotationParser:
    @staticmethod
    def is_quotation_pdf(pdf_path: str) -> bool:
        """True when the first page matches the CTI quotation PDF template."""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if not pdf.pages:
                    return False
                text = pdf.pages[0].extract_text() or ""
        except Exception:
            return False
        if "报价单" not in text:
            return False
        return any(marker in text for marker in _CONTENT_MARKERS)

    @staticmethod
    def extract_test_items(pdf_path: str) -> List[str]:
        """Extract service/test item names from a quotation PDF into a candidate list."""
        items: set[str] = set()
        target_col_idx = -1

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    if not table:
                        continue
                    for row in table:
                        cleaned = [
                            str(cell).replace("\n", "").strip() if cell else ""
                            for cell in row
                        ]

                        if target_col_idx == -1:
                            for i, cell in enumerate(cleaned):
                                if any(m in cell for m in _HEADER_MARKERS):
                                    target_col_idx = i
                                    break
                            if target_col_idx != -1:
                                # Skip the header row itself.
                                continue

                        if target_col_idx == -1:
                            continue

                        cell_text = (
                            cleaned[target_col_idx]
                            if target_col_idx < len(cleaned)
                            else ""
                        )
                        if not cell_text:
                            continue
                        if re.match(r"^[0-9\.\,]+$", cell_text):
                            continue
                        if cell_text in _SKIP_EXACT:
                            continue
                        if any(m in cell_text for m in _HEADER_MARKERS):
                            continue

                        items.add(cell_text)

        return sorted(items)
