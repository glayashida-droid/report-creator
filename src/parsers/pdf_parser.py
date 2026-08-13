import re
import pdfplumber
from typing import List

class QuotationParser:
    @staticmethod
    def extract_test_items(pdf_path: str) -> List[str]:
        items = set()
        
        # Find the column index for "服务项目"
        target_col_idx = -1
        
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                        
                    # First, identify the header row to find the "服务项目" column
                    for row_idx, row in enumerate(table):
                        # Clean row
                        cleaned_row = [str(cell).replace('\n', '').strip() if cell else "" for cell in row]
                        
                        if target_col_idx == -1:
                            for i, cell in enumerate(cleaned_row):
                                if "服务项目" in cell or "项目名称" in cell or "测试项目" in cell:
                                    target_col_idx = i
                                    break
                                    
                        # If we found the target column, start collecting from subsequent rows
                        if target_col_idx != -1 and row_idx > 0: # Assuming header is found
                            cell_text = cleaned_row[target_col_idx] if target_col_idx < len(cleaned_row) else ""
                            
                            if not cell_text:
                                continue
                                
                            # Skip obvious headers or numeric values
                            if re.match(r'^[0-9\.\,]+$', cell_text) or cell_text in ['序号', '项目名称', '测试项目', '服务项目', '单位', '数量', '单价', '总价', '备注']:
                                continue
                                
                            items.add(cell_text)
                            
        return sorted(list(items))
