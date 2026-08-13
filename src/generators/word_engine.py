import re
from pathlib import Path
from docx import Document
from src.models.project_state import ProjectState, TestNode, TestLeg

class WordGenerator:
    def __init__(self, template_path: str):
        self.template_path = template_path
        
    def generate(self, state: ProjectState, output_path: str, project_path: str = None, leg_filter: str = None):
        """
        Generate Word report. 
        leg_filter: "ALL" (default), or specific leg_id to generate for a single Leg.
        """
        doc = Document(self.template_path)
        
        # 1. Replace Placeholders in paragraphs
        placeholders = {
            "{{委托方名称}}": state.applicant_name,
            "{{委托方地址}}": state.applicant_address,
            "{{样品名称}}": state.sample_name,
            "{{样品接收日期}}": state.sample_receive_date,
            "{{检测开始日期}}": state.test_start_date,
            "{{检测结束日期}}": state.test_end_date,
            # we can add more if needed
        }
        
        for p in doc.paragraphs:
            self._replace_text_in_paragraph(p, placeholders)
            
        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        self._replace_text_in_paragraph(p, placeholders)
                        
        # 2. Extract nodes to generate
        nodes_to_generate = []
        if not leg_filter or leg_filter == "ALL":
            for leg in state.legs:
                nodes_to_generate.extend(leg.nodes)
        elif leg_filter.startswith("TEST:"):
            # Handle single test item filter
            test_target = leg_filter.replace("TEST:", "")
            for leg in state.legs:
                for node in leg.nodes:
                    if f"{leg.leg_name} - {node.test_name}" == test_target:
                        nodes_to_generate.append(node)
                        break
        else:
            for leg in state.legs:
                if leg.leg_id == leg_filter:
                    nodes_to_generate.extend(leg.nodes)
                    break
                    
        # 3. Dynamic Tables and Content
        if nodes_to_generate:
            doc.add_page_break()
            doc.add_heading("试验明细", level=1)
            
            for idx, node in enumerate(nodes_to_generate, 1):
                self._append_test_node(doc, node, idx, project_path)
                
        doc.save(output_path)
        
    def _replace_text_in_paragraph(self, paragraph, placeholders):
        """Simple text replacement in paragraph, taking runs into account is complex, 
        so we do a simple string replace if it matches exactly or piece it together."""
        # For simplicity, if the placeholder is fully within one run, we replace it.
        # If it spans runs, this basic approach might miss it. In production, a more 
        # robust run-stitching approach is needed (e.g. python-docx-template).
        text = paragraph.text
        has_changes = False
        for k, v in placeholders.items():
            if k in text:
                text = text.replace(k, str(v))
                has_changes = True
                
        if has_changes:
            # We clear runs and set the new text to the first run to keep basic styling
            if paragraph.runs:
                style = paragraph.runs[0].style
                paragraph.clear()
                paragraph.add_run(text, style)
            else:
                paragraph.text = text

    def _append_test_node(self, doc, node: TestNode, index: int, project_path: str = None):
        self._safe_add_heading(doc, f"{index}. {node.test_name}", level=2)
        
        # We append the 8 sub-sections as described in requirements
        self._safe_add_heading(doc, "1. 检测环境条件", level=3)
        doc.add_paragraph("环境温度: (23±2) ℃\n相对湿度: (50±5) %RH")
        
        self._safe_add_heading(doc, "2. 检测设备", level=3)
        doc.add_paragraph(f"设备名称: {node.equipment_name or '/'}")
        
        self._safe_add_heading(doc, "3. 检测方法", level=3)
        doc.add_paragraph(f"标准号: {node.standard_id or '/'}")
        
        self._safe_add_heading(doc, "4. 样品描述", level=3)
        # Assuming we just list the IDs
        s_ids = [s.sample_id for s in node.samples if s.sample_id]
        doc.add_paragraph(f"样品编号: {', '.join(s_ids) if s_ids else '/'}")
        
        self._safe_add_heading(doc, "5. 检测条件", level=3)
        doc.add_paragraph(node.standard_desc or "/")
        
        self._safe_add_heading(doc, "6. 数量", level=3)
        doc.add_paragraph(f"{len(node.samples)} pcs")
        
        self._safe_add_heading(doc, "7. 评判要求", level=3)
        doc.add_paragraph(node.evaluation_req or "/")
        
        self._safe_add_heading(doc, "8. 检测结果", level=3)
        
        # Build results table
        if node.samples:
            table = doc.add_table(rows=1, cols=2)
            # Default style that is almost always available
            try:
                table.style = 'Table Grid'
            except KeyError:
                pass # skip if template doesn't have it
                
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = '样品编号'
            hdr_cells[1].text = '结果'
            
            all_pass = True
            for sample in node.samples:
                row_cells = table.add_row().cells
                row_cells[0].text = sample.sample_id
                row_cells[1].text = sample.result.value
                if sample.result.value != "Pass":
                    all_pass = False
                    
            conclusion = "合格" if all_pass else "不合格"
            doc.add_paragraph(f"\n结论: {conclusion}")
        else:
            doc.add_paragraph("无结果记录")
            
        # 10. Test Photos
        if project_path and node.test_name:
            from src.generators.photo_scraper import PhotoScraper
            scraper = PhotoScraper(project_path)
            scraper.add_photos_to_document(doc, node.test_name)
            
    def _safe_add_heading(self, doc, text: str, level: int):
        try:
            doc.add_heading(text, level=level)
        except KeyError:
            # Fallback if template doesn't have heading styles
            p = doc.add_paragraph(text)
            p.runs[0].bold = True
