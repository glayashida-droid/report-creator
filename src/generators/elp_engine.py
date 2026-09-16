"""Fill the Geely ELP Word template from project state + ELP test plan."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches
from docx.table import Table

from src.generators.elp_docx import (
    cell_has_blue,
    cell_text,
    clone_table_row,
    delete_table_row,
    force_black_text,
    force_blue_text,
    iter_body_children,
    paragraph_style_name,
    remove_drawings,
    set_blue_portion,
    set_photo_caption,
    unique_cells,
    wrap_paragraph,
    wrap_table,
)
from src.generators.word_engine import PHOTO_WIDTH_IN, WordGenerator
from src.io.network_sources import elp_data_pattern_directory
from src.io.special_rules import DEFAULT_LAB_ADDRESS_CN, profile_from_state
from src.io.test_photos import is_image_file, list_sample_info_photos
from src.models.project_state import ProjectState, TestEquipment, TestNode
from src.parsers.elp_plan import (
    ElpPlan,
    caption_from_stem,
    elp_names_match,
    lookup_work_mode,
)

LAB_NAME_CN = "上海华测品正检测技术有限公司"
LAB_PHONE = "021-31073300"
LAB_ZIP = "201114"
DIFF_DEFAULT = "测试计划中的测试方式及相关条件与标准无差异"


class ElpExportFields:
    def __init__(
        self,
        rated_voltage: str = "",
        sample_source: str = "",
        plan_no: str = "",
    ):
        self.rated_voltage = (rated_voltage or "").strip()
        self.sample_source = (sample_source or "").strip()
        self.plan_no = (plan_no or "").strip()


class _TestBlock:
    def __init__(self, elements: List, heading_el, detail_tbl_el):
        self.elements = elements
        self.heading_el = heading_el
        self.detail_tbl_el = detail_tbl_el
        self.test_name = ""


class ElpReportGenerator:
    def __init__(self, template_path: str):
        self.template_path = template_path
        self._word = WordGenerator(template_path)
        self._word._report_language = "中文"
        self._export_temps: list = []

    def generate(
        self,
        state: ProjectState,
        output_path: str,
        *,
        project_path: Optional[str] = None,
        remote_root: Optional[str] = None,
        leg_filter: Optional[str] = None,
        report_no: str = "",
        extras: Optional[ElpExportFields] = None,
        plan: Optional[ElpPlan] = None,
        pattern_dir: Optional[Path] = None,
    ) -> None:
        extras = extras or ElpExportFields()
        plan = plan or ElpPlan()
        self._export_temps = []
        try:
            doc = Document(self.template_path)
            pairs = list(state.iter_nodes_for_export(leg_filter))
            nodes = [node for _leg, node in pairs]
            fields = state.overview_field_map("中文")
            self._fill_cover(doc, state, fields, extras, plan)
            self._fill_headers(doc, fields.get("试验类型") or "", report_no)
            self._fill_object_table(doc, state, fields, extras, plan, nodes)
            self._fill_lab_and_maker(doc, state, fields)
            self._fill_sample_photos(doc, project_path)
            self._fill_plan_chapter6(doc, plan, nodes)
            self._rewrite_chapter7(
                doc,
                state,
                pairs,
                fields,
                extras,
                plan,
                project_path,
                remote_root,
                pattern_dir,
            )
            self._fill_summary_table(doc, nodes)
            self._fill_diff_table(doc, nodes)
            doc.save(output_path)
        finally:
            for temp in self._export_temps:
                try:
                    Path(temp).unlink(missing_ok=True)
                except OSError:
                    pass
            self._export_temps = []

    # ------------------------------------------------------------------ cover / headers

    def _fill_cover(
        self,
        doc: Document,
        state: ProjectState,
        fields: Dict[str, str],
        extras: ElpExportFields,
        plan: ElpPlan,
    ) -> None:
        sample = fields.get("样品名称") or state.sample_name or plan.product_name
        part = fields.get("零件号") or plan.part_no
        project = fields.get("车型代码") or plan.vehicle_code
        test_type = fields.get("试验类型") or ""
        customer = fields.get("申请公司") or state.applicant_name
        address = fields.get("申请公司地址") or state.applicant_address
        mapping = {
            "零件名称": sample,
            "零部件号": part,
            "项目名称": project,
            "试验类型": test_type,
            "客户名称": customer,
            "客户地址": address,
        }
        for paragraph in doc.paragraphs[:20]:
            text = paragraph.text or ""
            for label, value in mapping.items():
                if label in text:
                    self._replace_paragraph_blue(paragraph, value)
                    break

    @staticmethod
    def _replace_paragraph_blue(paragraph, value: str) -> None:
        blue = [run for run in paragraph.runs if _run_is_blue(run)]
        if not blue:
            return
        blue[0].text = value or ""
        for run in blue[1:]:
            run.text = ""

    def _fill_headers(self, doc: Document, test_type: str, report_no: str) -> None:
        for section in doc.sections:
            parts = [section.header]
            try:
                if section.different_first_page_header_footer:
                    parts.append(section.first_page_header)
            except Exception:
                pass
            for part in parts:
                if part is None:
                    continue
                for paragraph in part.paragraphs:
                    text = paragraph.text or ""
                    if "试验类型" in text and test_type:
                        self._replace_paragraph_blue(paragraph, test_type)
                    if "报告编号" in text and report_no:
                        self._append_header_report_no(paragraph, report_no)

    @staticmethod
    def _append_header_report_no(paragraph, report_no: str) -> None:
        if report_no and report_no in (paragraph.text or ""):
            return
        from src.generators.elp_docx import set_run_color

        run = paragraph.add_run(report_no)
        set_run_color(run, "0000FF")

    # ------------------------------------------------------------------ early tables

    def _table_by_labels(self, doc: Document, *needles: str) -> Optional[Table]:
        for table in doc.tables:
            blob = "".join(cell_text(cell) for row in table.rows[:2] for cell in unique_cells(row))
            if all(n in blob for n in needles):
                return table
        return None

    def _fill_object_table(
        self,
        doc: Document,
        state: ProjectState,
        fields: Dict[str, str],
        extras: ElpExportFields,
        plan: ElpPlan,
        nodes: Sequence[TestNode],
    ) -> None:
        table = self._table_by_labels(doc, "车型代码", "样品名称")
        if table is None:
            return
        ids = WordGenerator._collect_sample_ids(nodes)
        id_text = WordGenerator._format_id_range(ids) if ids else "/"
        qty = (fields.get("送样数量") or "").strip()
        if not qty:
            qty = str(max((len([s for s in n.samples if s.sample_id]) for n in nodes), default=0) or "")
        values = {
            "车型代码": fields.get("车型代码") or plan.vehicle_code,
            "样品名称": fields.get("样品名称") or state.sample_name or plan.product_name,
            "零部件号": fields.get("零件号") or plan.part_no,
            "软件版本": plan.sw_version,
            "硬件版本": plan.hw_version,
            "样品数量": qty,
            "额定电压": extras.rated_voltage,
            "样品编号": id_text,
            "来样方式": extras.sample_source,
            "样品接收日期": WordGenerator._fmt_date(state.sample_receive_date),
            "测试开始时间": WordGenerator._fmt_date(state.test_start_date),
            "测试结束时间": WordGenerator._fmt_date(state.test_end_date),
        }
        for row in table.rows:
            cells = unique_cells(row)
            if len(cells) < 2:
                continue
            label = cell_text(cells[0])
            for key, val in values.items():
                if label.startswith(key):
                    self._write_blue(cells[1], val)
                    break

    def _fill_lab_and_maker(
        self, doc: Document, state: ProjectState, fields: Dict[str, str]
    ) -> None:
        profile = profile_from_state(state)
        lab_addr = (profile.lab_address_cn or "").strip() or DEFAULT_LAB_ADDRESS_CN
        lab = self._table_by_labels(doc, "名称", "E-mail")
        if lab is not None and cell_text(unique_cells(lab.rows[0])[0]) == "名称":
            mapping = {
                "名称": LAB_NAME_CN,
                "地址": lab_addr,
                "电话": LAB_PHONE,
                "传真": "/",
                "邮编": LAB_ZIP,
                "E-mail": "/",
            }
            self._fill_kv_table(lab, mapping)
        maker = self._table_by_labels(doc, "制造商", "邮编")
        if maker is not None:
            producer = fields.get("生产商") or fields.get("申请公司") or state.applicant_name
            addr = (
                fields.get("生产商地址")
                or fields.get("申请公司地址")
                or state.applicant_address
            )
            self._fill_kv_table(
                maker,
                {
                    "制造商": producer,
                    "地址": addr,
                    "电话": "/",
                    "传真": "/",
                    "邮编": "/",
                },
            )

    @staticmethod
    def _fill_kv_table(table: Table, mapping: Dict[str, str]) -> None:
        for row in table.rows:
            cells = unique_cells(row)
            if len(cells) < 2:
                continue
            label = cell_text(cells[0])
            for key, val in mapping.items():
                if label.startswith(key):
                    set_blue_portion(cells[1], val)
                    break

    def _fill_sample_photos(self, doc: Document, project_path: Optional[str]) -> None:
        table = None
        for candidate in doc.tables:
            blob = "".join(
                cell_text(cell) for row in candidate.rows for cell in unique_cells(row)
            )
            if "测试样品照" in blob:
                table = candidate
                break
        if table is None:
            return
        photos: List[Path] = []
        if project_path:
            photos = list_sample_info_photos(Path(project_path))
        slots = [
            (1, 0),
            (1, 1),
            (3, 0),
            (3, 1),
        ]
        image_rows = {1: 0, 3: 2}
        for i, (cap_r, cap_c) in enumerate(slots):
            if cap_r >= len(table.rows):
                continue
            cap_cells = unique_cells(table.rows[cap_r])
            img_r = image_rows[cap_r]
            if img_r >= len(table.rows) or cap_c >= len(cap_cells):
                continue
            img_cells = unique_cells(table.rows[img_r])
            cap_cell = cap_cells[cap_c]
            img_cell = img_cells[cap_c] if cap_c < len(img_cells) else cap_cell
            remove_drawings(img_cell)
            if i < len(photos):
                path = photos[i]
                force_blue_text(cap_cell, path.stem)
                self._put_picture(img_cell, path)
            else:
                force_blue_text(cap_cell, "")

    # ------------------------------------------------------------------ chapter 6

    def _fill_plan_chapter6(
        self, doc: Document, plan: ElpPlan, nodes: Sequence[TestNode]
    ) -> None:
        basic = self._table_by_labels(doc, "电子电器组件种类", "工作类型")
        if basic is not None:
            self._fill_basic_ticks(basic, plan)
        modes = None
        klass = None
        for table in doc.tables:
            head = cell_text(unique_cells(table.rows[0])[0]) if table.rows else ""
            blob = "".join(cell_text(c) for r in table.rows[:2] for c in unique_cells(r))
            if head == "工作模式" and "定义描述" in blob and modes is None:
                modes = table
            elif "产品功能分类" in blob and klass is None:
                klass = table
        if klass is not None and plan.function_class_rows:
            self._replace_function_class(klass, plan.function_class_rows)
        if modes is not None and plan.work_mode_defs:
            self._fill_work_mode_defs(modes, plan)
        monitor = self._table_by_labels(doc, "功能描述", "可接受范围")
        if monitor is not None and plan.monitor_rows:
            self._replace_simple_rows(monitor, plan.monitor_rows, 3)
        states = self._table_by_labels(doc, "功能状态", "定义描述")
        if states is not None and plan.function_states:
            self._fill_function_states(states, plan.function_states)

    def _fill_basic_ticks(self, table: Table, plan: ElpPlan) -> None:
        i = 0
        rows = table.rows
        while i < len(rows):
            cells = unique_cells(rows[i])
            label = cell_text(cells[0]) if cells else ""
            if label in plan.basic_ticks and i + 1 < len(rows):
                headers = unique_cells(rows[i])
                ticks = unique_cells(rows[i + 1])
                wanted = set(plan.basic_ticks[label])
                for idx in range(1, min(len(headers), len(ticks))):
                    option = cell_text(headers[idx])
                    set_blue_portion(ticks[idx], "√" if option in wanted else "")
                i += 2
                continue
            if label == "更多相关信息描述" and i + 1 < len(rows):
                headers = unique_cells(rows[i])
                values = unique_cells(rows[i + 1])
                for idx in range(1, min(len(headers), len(values))):
                    key = cell_text(headers[idx])
                    if key in plan.extra_info:
                        set_blue_portion(values[idx], plan.extra_info[key])
                i += 2
                continue
            i += 1

    def _replace_function_class(self, table: Table, pdf_rows: Sequence[Sequence[str]]) -> None:
        # Keep header rows 0-1 and trailing 备注 row if present.
        note_idx = None
        for idx, row in enumerate(table.rows):
            if "备注" in cell_text(unique_cells(row)[0]):
                note_idx = idx
                break
        data_start = 2
        data_end = note_idx if note_idx is not None else len(table.rows)
        pdf_data = [row for row in pdf_rows[2:] if row and not "".join(row).startswith("备注")]
        while (data_end - data_start) > len(pdf_data) and data_end - 1 > data_start:
            delete_table_row(table, data_end - 1)
            data_end -= 1
        while (data_end - data_start) < len(pdf_data):
            clone_table_row(table, data_start)
            data_end += 1
        for offset, pdf_row in enumerate(pdf_data):
            cells = unique_cells(table.rows[data_start + offset])
            for idx, cell in enumerate(cells):
                value = pdf_row[idx] if idx < len(pdf_row) else ""
                if idx == 0:
                    force_black_text(cell, value)
                else:
                    set_blue_portion(cell, value) or force_blue_text(cell, value)

    def _fill_work_mode_defs(self, table: Table, plan: ElpPlan) -> None:
        by_mode = {normalize_mode(m): d for m, d in plan.work_mode_defs}
        for row in table.rows[1:]:
            cells = unique_cells(row)
            if len(cells) < 2:
                continue
            key = normalize_mode(cell_text(cells[0]))
            if key in by_mode:
                set_blue_portion(cells[1], by_mode[key])
        if plan.work_mode_notes:
            last = unique_cells(table.rows[-1])
            if last and "备注" not in cell_text(last[0]):
                clone_table_row(table, len(table.rows) - 1)
                cells = unique_cells(table.rows[-1])
                force_black_text(cells[0], "备注")
                force_blue_text(cells[1] if len(cells) > 1 else cells[0], plan.work_mode_notes)

    def _replace_simple_rows(
        self, table: Table, rows: Sequence[Tuple[str, str, str]], cols: int
    ) -> None:
        while len(table.rows) - 1 > len(rows) and len(table.rows) > 2:
            delete_table_row(table, len(table.rows) - 1)
        while len(table.rows) - 1 < len(rows):
            clone_table_row(table, 1)
        for idx, values in enumerate(rows):
            cells = unique_cells(table.rows[idx + 1])
            for col in range(min(cols, len(cells))):
                force_blue_text(cells[col], values[col] if col < len(values) else "")

    def _fill_function_states(
        self, table: Table, states: Sequence[Tuple[str, str]]
    ) -> None:
        by_name = {name: desc for name, desc in states}
        for row in table.rows[1:]:
            cells = unique_cells(row)
            if len(cells) < 2:
                continue
            name = cell_text(cells[0])
            if name in by_name:
                set_blue_portion(cells[1], by_name[name])

    def _fill_summary_table(self, doc: Document, nodes: Sequence[TestNode]) -> None:
        table = self._table_by_labels(doc, "试验项目", "试验标准", "结果判定")
        if table is None:
            return
        originals = []
        for row in table.rows[1:]:
            cells = unique_cells(row)
            if len(cells) < 4:
                continue
            originals.append(
                (cell_text(cells[1]), cell_text(cells[2]), cells)
            )
        template_tr = deepcopy(table.rows[1]._tr) if len(table.rows) > 1 else None
        while len(table.rows) > 1:
            delete_table_row(table, 1)
        if template_tr is None:
            return
        for idx, node in enumerate(nodes):
            table._tbl.append(deepcopy(template_tr))
            cells = unique_cells(table.rows[-1])
            name = (node.test_name or "").strip()
            std = ""
            matched = next((item for item in originals if elp_names_match(item[0], name)), None)
            if matched:
                name = matched[0]
                std = matched[1]
            else:
                std = WordGenerator._format_method(node) or "/"
            force_black_text(cells[0], str(idx + 1))
            force_black_text(cells[1], name)
            force_black_text(cells[2], std)
            force_blue_text(cells[3], self._conclusion(node))

    def _fill_diff_table(self, doc: Document, nodes: Sequence[TestNode]) -> None:
        table = self._table_by_labels(doc, "测试项目", "测试方法差异说明")
        if table is None:
            return
        originals = []
        for row in table.rows[1:]:
            cells = unique_cells(row)
            if len(cells) < 2:
                continue
            originals.append(cell_text(cells[0]))
        template_tr = deepcopy(table.rows[1]._tr) if len(table.rows) > 1 else None
        while len(table.rows) > 1:
            delete_table_row(table, 1)
        if template_tr is None:
            return
        for node in nodes:
            table._tbl.append(deepcopy(template_tr))
            cells = unique_cells(table.rows[-1])
            name = (node.test_name or "").strip()
            matched = next((item for item in originals if elp_names_match(item, name)), None)
            force_black_text(cells[0], matched or name)
            force_blue_text(cells[1], DIFF_DEFAULT)

    # ------------------------------------------------------------------ chapter 7

    def _rewrite_chapter7(
        self,
        doc: Document,
        state: ProjectState,
        pairs: Sequence[Tuple],
        fields: Dict[str, str],
        extras: ElpExportFields,
        plan: ElpPlan,
        project_path: Optional[str],
        remote_root: Optional[str],
        pattern_dir: Optional[Path],
    ) -> None:
        blocks = self._collect_test_blocks(doc)
        if not blocks:
            return
        prototype = deepcopy(blocks[0].elements)
        used = set()
        ordered: List[Tuple[TestNode, List, bool, str]] = []
        for leg, node in pairs:
            match = None
            for idx, block in enumerate(blocks):
                if idx in used:
                    continue
                if elp_names_match(node.test_name, block.test_name):
                    match = block
                    used.add(idx)
                    break
            if match is not None:
                ordered.append((node, match.elements, True, leg.leg_name))
            else:
                ordered.append(
                    (node, [deepcopy(el) for el in prototype], False, leg.leg_name)
                )
        self._remove_elements(doc, [el for block in blocks for el in block.elements])
        anchor = self._chapter7_anchor(doc)
        parent = doc.element.body
        insert_at = list(parent).index(anchor) + 1 if anchor is not None else len(list(parent)) - 1
        for idx, (node, elements, matched, leg_name) in enumerate(ordered):
            for el in elements:
                parent.insert(insert_at, el)
                insert_at += 1
            self._fill_test_block(
                doc,
                elements,
                node,
                index=idx + 1,
                matched=matched,
                leg_name=leg_name,
                state=state,
                fields=fields,
                extras=extras,
                plan=plan,
                project_path=project_path,
                remote_root=remote_root,
                pattern_dir=pattern_dir,
            )

    def _chapter7_anchor(self, doc):
        for child in iter_body_children(doc):
            if child.tag != qn("w:p"):
                continue
            paragraph = wrap_paragraph(child, doc)
            if paragraph_style_name(paragraph).startswith("Heading 1") and "检测项目" in (
                paragraph.text or ""
            ):
                return child
        return None

    def _collect_test_blocks(self, doc: Document) -> List[_TestBlock]:
        started = False
        blocks: List[_TestBlock] = []
        current: List = []
        heading_el = None
        detail_el = None
        for child in iter_body_children(doc):
            if child.tag == qn("w:p"):
                paragraph = wrap_paragraph(child, doc)
                style = paragraph_style_name(paragraph)
                text = (paragraph.text or "").strip()
                if style.startswith("Heading 1") and "检测项目" in text:
                    started = True
                    continue
                if not started:
                    continue
                if style.startswith("Heading 2"):
                    if current and heading_el is not None:
                        block = _TestBlock(current, heading_el, detail_el)
                        block.test_name = self._block_name(doc, block)
                        blocks.append(block)
                    current = [child]
                    heading_el = child
                    detail_el = None
                    continue
            if started and current:
                current.append(child)
                if child.tag == qn("w:tbl") and detail_el is None:
                    detail_el = child
        if started and current and heading_el is not None:
            block = _TestBlock(current, heading_el, detail_el)
            block.test_name = self._block_name(doc, block)
            blocks.append(block)
        return blocks

    def _block_name(self, doc: Document, block: _TestBlock) -> str:
        if block.heading_el is not None:
            name = (wrap_paragraph(block.heading_el, doc).text or "").strip()
            if name:
                return name
        if block.detail_tbl_el is None:
            return ""
        table = wrap_table(block.detail_tbl_el, doc)
        for row in table.rows:
            cells = unique_cells(row)
            if len(cells) >= 3 and "试验项目" in cell_text(cells[1]):
                return cell_text(cells[2])
        return ""

    @staticmethod
    def _remove_elements(doc: Document, elements: Sequence) -> None:
        body = doc.element.body
        for el in elements:
            parent = el.getparent()
            if parent is body:
                body.remove(el)

    def _fill_test_block(
        self,
        doc: Document,
        elements: List,
        node: TestNode,
        *,
        index: int,
        matched: bool,
        leg_name: str,
        state: ProjectState,
        fields: Dict[str, str],
        extras: ElpExportFields,
        plan: ElpPlan,
        project_path: Optional[str],
        remote_root: Optional[str],
        pattern_dir: Optional[Path],
    ) -> None:
        tables = [wrap_table(el, doc) for el in elements if el.tag == qn("w:tbl")]
        if not tables:
            return
        detail = tables[0]
        self._renumber_detail(detail, index)
        sample_name = fields.get("样品名称") or state.sample_name or ""
        qty = str(len([s for s in (node.samples or []) if s.sample_id]) or "")
        plan_no = extras.plan_no or plan.plan_no
        mode = lookup_work_mode(plan.test_work_modes, node.test_name)
        env = node.resolved_env_condition() or "/"
        period = self._period(node.start_date, node.end_date)
        tester = (state.tester_name or "").strip() or "/"
        result_text = self._result_text(node)
        conclusion = self._conclusion(node)
        method = WordGenerator._format_method(node) or "/"
        standard = method
        eval_req = (node.evaluation_req or node.joined_evaluation_req() or "").strip()
        for row in detail.rows:
            cells = unique_cells(row)
            if len(cells) < 3:
                continue
            label = cell_text(cells[1])
            value_cell = cells[2]
            if "样品名称" in label:
                self._write_blue(value_cell, sample_name)
            elif "试验项目" in label:
                if not matched:
                    force_black_text(value_cell, node.test_name or "")
            elif "试验标准" in label:
                if not matched:
                    force_black_text(value_cell, standard)
            elif "工作模式" in label:
                if mode:
                    self._write_blue(value_cell, mode)
            elif "样品" in label and "数量" in label:
                self._write_blue(value_cell, qty)
            elif "试验地点" in label:
                self._write_blue(value_cell, LAB_NAME_CN)
            elif "试验室温湿度" in label:
                self._write_blue(value_cell, env)
            elif "试验人员" in label:
                self._write_blue(value_cell, tester)
            elif "试验起止日期" in label:
                self._write_blue(value_cell, period)
            elif "测试计划编号" in label:
                self._write_blue(value_cell, plan_no)
            elif "试验方法" in label:
                if not matched:
                    force_black_text(value_cell, method)
            elif "试验要求" in label:
                if eval_req and (cell_has_blue(value_cell) or not matched):
                    if matched:
                        set_blue_portion(value_cell, eval_req)
                    else:
                        force_black_text(value_cell, eval_req)
            elif "试验结果" in label:
                self._write_blue(value_cell, result_text)
            elif "结果判定" in label:
                self._write_blue(value_cell, conclusion)
            elif label.startswith("备注"):
                set_blue_portion(value_cell, "/")
        self._fill_equipment_rows(detail, node)
        heading = next((el for el in elements if el.tag == qn("w:p")), None)
        if heading is not None and not matched:
            paragraph = wrap_paragraph(heading, doc)
            if paragraph.runs:
                paragraph.runs[0].text = node.test_name or ""
                for run in paragraph.runs[1:]:
                    run.text = ""
        photo_tables = tables[1:]
        self._fill_photo_tables(
            photo_tables,
            node,
            leg_name=leg_name,
            project_path=project_path,
            remote_root=remote_root,
            pattern_dir=pattern_dir,
            matched=matched,
        )

    @staticmethod
    def _renumber_detail(table: Table, index: int) -> None:
        import re

        for row_i, row in enumerate(table.rows):
            cells = unique_cells(row)
            if not cells:
                continue
            raw = cell_text(cells[0])
            updated = re.sub(r"7\.\d+", f"7.{index}", raw, count=1)
            if updated != raw:
                force_black_text(cells[0], updated)

    def _fill_equipment_rows(self, table: Table, node: TestNode) -> None:
        items = list(node.equipments or [])
        if not items and node.equipment_name:
            items = [TestEquipment(name=node.equipment_name)]
        eq_rows = []
        for idx, row in enumerate(table.rows):
            cells = unique_cells(row)
            if len(cells) >= 3 and "试验设备" in cell_text(cells[1]):
                eq_rows.append(idx)
        if len(eq_rows) < 2:
            return
        data_idx = eq_rows[1:]
        while len(data_idx) < max(len(items), 1):
            clone_table_row(table, data_idx[-1])
            data_idx.append(len(table.rows) - 1)
        for offset, row_i in enumerate(data_idx):
            cells = unique_cells(table.rows[row_i])
            if len(cells) < 6:
                continue
            if offset < len(items):
                eq = items[offset]
                vals = [
                    (eq.name or "").replace("\n", "") or "/",
                    eq.model or "/",
                    eq.code or "/",
                    (eq.valid_date or "").strip() or "/",
                ]
            else:
                vals = ["/", "/", "/", "/"]
            for col, val in enumerate(vals, start=2):
                self._write_blue(cells[col], val)

    def _fill_photo_tables(
        self,
        tables: Sequence[Table],
        node: TestNode,
        *,
        leg_name: str,
        project_path: Optional[str],
        remote_root: Optional[str],
        pattern_dir: Optional[Path],
        matched: bool,
    ) -> None:
        photos = self._collect_photos(
            node, leg_name, project_path, remote_root, pattern_dir
        )
        slots = []
        for table in tables:
            title_cells = unique_cells(table.rows[0]) if table.rows else []
            if title_cells and not matched:
                name = (node.test_name or "").strip()
                force_black_text(title_cells[0], f"{name} 相关图片：")
            for cap_row in (2, 4, 6, 8):
                if cap_row >= len(table.rows):
                    continue
                img_row = cap_row - 1
                cap_cells = unique_cells(table.rows[cap_row])
                img_cells = unique_cells(table.rows[img_row])
                for col, cap_cell in enumerate(cap_cells):
                    img_cell = img_cells[col] if col < len(img_cells) else cap_cell
                    slots.append((cap_cell, img_cell))
        for i, (cap_cell, img_cell) in enumerate(slots):
            remove_drawings(img_cell)
            if i < len(photos):
                path = photos[i]
                set_photo_caption(cap_cell, i + 1, caption_from_stem(path.stem))
                self._put_picture(img_cell, path)
            else:
                set_photo_caption(cap_cell, i + 1, "/")

    def _collect_photos(
        self,
        node: TestNode,
        leg_name: str,
        project_path: Optional[str],
        remote_root: Optional[str],
        pattern_dir: Optional[Path],
    ) -> List[Path]:
        from src.io.project_assets import iter_merged_export_photos

        photos: List[Path] = []
        if project_path and node.test_name and leg_name:
            for item in iter_merged_export_photos(
                Path(project_path),
                Path(remote_root) if remote_root else None,
                leg_name,
                node.test_name,
                order=getattr(node, "photo_album_order", None) or None,
                temps=self._export_temps,
            ):
                photos.append(item.path)
        photos.extend(self._pattern_photos(node.test_name or "", pattern_dir))
        return photos

    @staticmethod
    def _pattern_photos(test_name: str, pattern_dir: Optional[Path]) -> List[Path]:
        if pattern_dir is None:
            pattern_dir = elp_data_pattern_directory()
        root = Path(pattern_dir)
        try:
            if not root.is_dir() or not test_name:
                return []
            folder = root / test_name
            if not folder.is_dir():
                folder = next(
                    (
                        child
                        for child in root.iterdir()
                        if child.is_dir() and elp_names_match(child.name, test_name)
                    ),
                    None,
                )
            if folder is None or not folder.is_dir():
                return []
            photos = [p for p in folder.iterdir() if is_image_file(p)]
        except OSError:
            return []
        photos.sort(key=lambda p: p.name.casefold())
        return photos

    def _put_picture(self, cell, path: Path) -> None:
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in list(paragraph.runs):
            run._element.getparent().remove(run._element)
        try:
            stream = self._word._prepare_embed_stream(path, PHOTO_WIDTH_IN)
            run = paragraph.add_run()
            run.add_picture(stream, width=Inches(PHOTO_WIDTH_IN))
        except Exception:
            paragraph.add_run(f"[无法插入图片: {path.name}]")

    @staticmethod
    def _write_blue(cell, value: str) -> None:
        if not set_blue_portion(cell, value):
            force_blue_text(cell, value)

    @staticmethod
    def _period(start: Optional[str], end: Optional[str]) -> str:
        a = WordGenerator._fmt_date(start)
        b = WordGenerator._fmt_date(end)
        if a and b:
            return f"{a}-{b}"
        return a or b or "/"

    @staticmethod
    def _conclusion(node: TestNode) -> str:
        return _node_conclusion_zh(node)

    @staticmethod
    def _result_text(node: TestNode) -> str:
        samples = [s for s in (node.samples or []) if s.sample_id]
        stds = node.result_table_standards()
        lines = []
        for sample in samples:
            desc = ""
            if stds:
                desc = (sample.desc_for(stds[0]) or stds[0].result_desc or "").strip()
            desc = desc or (sample.result_desc or node.result_desc or "").strip()
            lines.append(f"{sample.sample_id}：{desc or '/'}")
        return "\n".join(lines) if lines else "/"


def _run_is_blue(run) -> bool:
    from src.generators.elp_docx import run_is_blue

    return run_is_blue(run)


def _node_conclusion_zh(node: TestNode) -> str:
    engine = WordGenerator.__new__(WordGenerator)
    engine._report_language = "中文"
    return WordGenerator._node_conclusion(engine, node)


def normalize_mode(text: str) -> str:
    return (text or "").replace(" ", "").casefold()
