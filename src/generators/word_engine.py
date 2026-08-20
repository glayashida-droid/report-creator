import re
from pathlib import Path
from docx import Document
from src.models.project_state import ProjectState, TestNode, TestLeg, TestResult

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
        placeholders = self._build_placeholders(state)
        
        for p in doc.paragraphs:
            self._replace_text_in_paragraph(p, placeholders)
            
        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        self._replace_text_in_paragraph(p, placeholders)

        self._append_overview_table(doc, state)
                        
        # 2. Extract nodes to generate
        nodes_to_generate = [node for _, node in state.iter_nodes_for_export(leg_filter)]
                    
        # 3. Dynamic Tables and Content
        if nodes_to_generate:
            doc.add_page_break()
            doc.add_heading("试验明细", level=1)
            
            for idx, node in enumerate(nodes_to_generate, 1):
                self._append_test_node(doc, node, idx, project_path)
                
        doc.save(output_path)

    def _build_placeholders(self, state: ProjectState):
        visible = dict(state.iter_overview_fields())
        placeholders = {
            "{{委托方名称}}": visible.get("申请公司", ""),
            "{{委托方地址}}": visible.get("申请公司地址", ""),
            "{{样品名称}}": visible.get("样品名称", ""),
            "{{样品接收日期}}": state.sample_receive_date or "",
            "{{检测开始日期}}": state.test_start_date or "",
            "{{检测结束日期}}": state.test_end_date or "",
            "{{申请单号}}": visible.get("申请单号", ""),
            "{{报告抬头公司}}": visible.get("报告抬头公司", ""),
            "{{报告抬头地址}}": visible.get("报告抬头地址", ""),
        }
        for key, val in visible.items():
            placeholders["{{%s}}" % key] = val
        for key in state.excluded_overview_keys or []:
            placeholders.setdefault("{{%s}}" % key, "")
            if key == "申请公司":
                placeholders["{{委托方名称}}"] = ""
            elif key == "申请公司地址":
                placeholders["{{委托方地址}}"] = ""
            elif key == "样品名称":
                placeholders["{{样品名称}}"] = ""
        return placeholders

    def _append_overview_table(self, doc, state: ProjectState):
        rows = list(state.iter_overview_fields())
        if not rows:
            return
        self._safe_add_heading(doc, "项目信息", level=1)
        table = doc.add_table(rows=1, cols=2)
        try:
            table.style = "Table Grid"
        except KeyError:
            pass
        hdr = table.rows[0].cells
        hdr[0].text = "字段"
        hdr[1].text = "内容"
        for key, val in rows:
            cells = table.add_row().cells
            cells[0].text = key
            cells[1].text = val
        
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
        doc.add_paragraph(self._format_equipments(node))
        
        self._safe_add_heading(doc, "3. 检测方法", level=3)
        doc.add_paragraph(node.joined_test_method() or "/")
        
        self._safe_add_heading(doc, "4. 样品描述", level=3)
        s_ids = [s.sample_id for s in node.samples if s.sample_id]
        doc.add_paragraph(f"样品编号: {', '.join(s_ids) if s_ids else '/'}")
        
        self._safe_add_heading(doc, "5. 检测条件", level=3)
        doc.add_paragraph(node.standard_desc or node.joined_standard_desc() or "/")
        
        self._safe_add_heading(doc, "6. 数量", level=3)
        doc.add_paragraph(f"{len(node.samples)} pcs")
        
        self._safe_add_heading(doc, "7. 评判要求", level=3)
        doc.add_paragraph(node.evaluation_req or node.joined_evaluation_req() or "/")
        
        self._safe_add_heading(doc, "8. 检测结果", level=3)
        self._append_result_desc_table(doc, node)
        self._append_sample_result_table(doc, node)
            
        # 10. Test Photos
        if project_path and node.test_name:
            from src.generators.photo_scraper import PhotoScraper
            scraper = PhotoScraper(project_path)
            scraper.add_photos_to_document(doc, node.test_name)

    def _style_table(self, table):
        try:
            table.style = "Table Grid"
        except KeyError:
            pass

    def _append_result_desc_table(self, doc, node: TestNode):
        stds = node.resolved_standards()
        if not stds:
            doc.add_paragraph("无结果描述")
            return
        table = doc.add_table(rows=1, cols=4)
        self._style_table(table)
        hdr = table.rows[0].cells
        hdr[0].text = "标准号"
        hdr[1].text = "章节号"
        hdr[2].text = "试验名称"
        hdr[3].text = "结果描述"
        for std in stds:
            cells = table.add_row().cells
            cells[0].text = std.standard_id or "/"
            cells[1].text = std.chapter or "/"
            cells[2].text = std.test_name or "/"
            cells[3].text = std.result_desc or "/"

    def _append_sample_result_table(self, doc, node: TestNode):
        if not node.samples:
            doc.add_paragraph("无结果记录")
            return
        table = doc.add_table(rows=1, cols=3)
        self._style_table(table)
        hdr = table.rows[0].cells
        hdr[0].text = "样品编号"
        hdr[1].text = "结果描述"
        hdr[2].text = "结果"
        all_pass = True
        node_desc = getattr(node, "result_desc", None) or ""
        for sample in node.samples:
            cells = table.add_row().cells
            cells[0].text = sample.sample_id
            cells[1].text = getattr(sample, "result_desc", None) or node_desc or "/"
            cells[2].text = sample.result.value
            if sample.result != TestResult.PASS:
                all_pass = False
        conclusion = "合格" if all_pass else "不合格"
        doc.add_paragraph(f"\n结论: {conclusion}")

    def _format_equipments(self, node: TestNode) -> str:
        items = getattr(node, "equipments", None) or []
        if items:
            lines = []
            for eq in items:
                parts = [p for p in (eq.code, eq.name) if p]
                if eq.model:
                    parts.append(f"({eq.model})")
                lines.append(" ".join(parts) if parts else "/")
            return "\n".join(lines)
        return f"设备名称: {node.equipment_name or '/'}"
            
    def _safe_add_heading(self, doc, text: str, level: int):
        try:
            doc.add_heading(text, level=level)
        except KeyError:
            # Fallback if template doesn't have heading styles
            p = doc.add_paragraph(text)
            p.runs[0].bold = True
