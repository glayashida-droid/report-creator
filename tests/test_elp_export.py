from pathlib import Path

from PIL import Image

from src.generators.elp_docx import cell_text, unique_cells
from src.generators.elp_engine import ElpExportFields, ElpReportGenerator
from src.io.network_sources import ELP_REPORT_LANGUAGE, REPORT_LANGUAGE_CHOICES
from src.io.project_mirror import repo_root
from src.io.test_photos import (
    SAMPLE_INFO_DIR_NAME,
    create_album,
    ensure_sample_info_dir,
    list_sample_info_photos,
)
from src.models.project_state import (
    ProjectState,
    TestEquipment,
    TestLeg,
    TestNode,
    TestResult,
    TestSample,
    TestStandard,
)
from src.parsers.elp_plan import ElpPlan


TEMPLATE = repo_root() / "templates" / "report_templates" / "ELP 零部件试验报告模板 - 更新中.docx"
LEG = "Leg 1"


def _png(path: Path, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path, "PNG")
    return path


def test_language_choices_include_elp():
    assert REPORT_LANGUAGE_CHOICES[-1] == ELP_REPORT_LANGUAGE
    assert "中文" in REPORT_LANGUAGE_CHOICES


def test_sample_info_dir_created_with_album(tmp_path: Path):
    project = tmp_path / "proj"
    create_album(project, LEG, "启动脉冲", "试验前")
    folder = project / "3.测试组" / SAMPLE_INFO_DIR_NAME
    assert folder.is_dir()
    photo = _png(folder / "正面.png")
    listed = list_sample_info_photos(project)
    assert listed == [photo]
    ensure_sample_info_dir(project)
    assert folder.is_dir()


def test_elp_export_fields_trim_values():
    fields = ElpExportFields(
        rated_voltage=" 12V ",
        sample_source=" 送样 ",
        plan_no="  P166-ELP-TP(副仪表板开关组)-2026-0001  ",
    )
    assert fields.rated_voltage == "12V"
    assert fields.sample_source == "送样"
    assert fields.plan_no == "P166-ELP-TP(副仪表板开关组)-2026-0001"


def _state(project: Path) -> ProjectState:
    node_match = TestNode(
        test_name="启动脉冲",
        standards=[
            TestStandard(
                standard_id="Q/JLY J7111029E-2024",
                chapter="5.2",
                test_name="启动脉冲",
                standard_desc="冷启动/热启动",
                evaluation_req="功能状态A",
                result_desc="功能正常",
            )
        ],
        equipments=[
            TestEquipment(
                name="可编程电源",
                model="NGI",
                code="EQ-1",
                valid_date="2027-01-01",
            )
        ],
        start_date="2026-08-02",
        end_date="2026-08-03",
        env_condition="25℃/50%RH",
        samples=[
            TestSample(sample_id="A01", result=TestResult.PASS, result_desc="功能正常"),
        ],
    )
    node_extra = TestNode(
        test_name="自定义过压",
        standard_id="Q/JLY J7111029E-2024",
        standard_chapter="9.9",
        standard_desc="自定义条件",
        evaluation_req="功能状态A",
        result_desc="功能正常",
        equipment_name="直流电源",
        start_date="2026-08-04",
        end_date="2026-08-05",
        samples=[
            TestSample(sample_id="A01", result=TestResult.PASS, result_desc="功能正常"),
        ],
    )
    return ProjectState(
        project_id="A2260745791101",
        applicant_name="吉利汽车",
        applicant_address="杭州",
        sample_name="副仪表板开关组",
        sample_receive_date="2026-08-01",
        test_start_date="2026-08-02",
        test_end_date="2026-08-10",
        tester_name="测试员",
        application_fields={
            "申请单号": "A22607457911",
            "申请公司": "吉利汽车",
            "申请公司地址": "杭州",
            "样品名称": "副仪表板开关组",
            "零件号": "6608707284",
            "车型代码": "P166",
            "试验类型": "ELP",
            "送样数量": "1",
        },
        legs=[
            TestLeg(leg_id="L1", leg_name=LEG, nodes=[node_match, node_extra]),
        ],
    )


def test_elp_engine_keeps_program_tests_and_fills_fields(tmp_path: Path):
    if not TEMPLATE.is_file():
        return
    project = tmp_path / "proj"
    album = create_album(project, LEG, "启动脉冲", "试验前")
    _png(album / "布置.png")
    sample_dir = project / "3.测试组" / SAMPLE_INFO_DIR_NAME
    _png(sample_dir / "正面.png")
    pattern = tmp_path / "patten" / "启动脉冲"
    _png(pattern / "图片10：校准图冷启动t6.png")

    out = tmp_path / "elp.docx"
    plan = ElpPlan(
        product_name="副仪表板开关组",
        vehicle_code="P166",
        part_no="6608707284",
        hw_version="V1.0",
        sw_version="V1.0",
        plan_no="P166-ELP-TP(副仪表板开关组)-2026-0001",
        test_work_modes={"启动脉冲": "工作模式2.2"},
        monitor_rows=[("1", "背光灯点亮", "无闪烁")],
    )
    extras = ElpExportFields(
        rated_voltage="12V",
        sample_source="送样",
        plan_no=plan.plan_no,
    )
    ElpReportGenerator(str(TEMPLATE)).generate(
        _state(project),
        str(out),
        extras=extras,
        plan=plan,
        project_path=str(project),
        pattern_dir=tmp_path / "patten",
        report_no="A226074579110100001E",
    )
    from docx import Document
    from docx.oxml.ns import qn

    from src.generators.elp_docx import iter_body_children, paragraph_style_name, wrap_paragraph

    doc = Document(str(out))
    headings = []
    for child in iter_body_children(doc):
        if child.tag != qn("w:p"):
            continue
        paragraph = wrap_paragraph(child, doc)
        if paragraph_style_name(paragraph).startswith("Heading 2"):
            headings.append((paragraph.text or "").strip())
    assert "启动脉冲" in headings
    assert "自定义过压" in headings
    assert "反极性" not in headings
    assert headings.count("启动脉冲") == 1

    summary = None
    object_table = None
    sample_table = None
    for table in doc.tables:
        blob = "".join(cell_text(c) for r in table.rows for c in unique_cells(r))
        head = "".join(cell_text(c) for r in table.rows[:2] for c in unique_cells(r))
        if "试验项目" in head and "结果判定" in head:
            summary = table
        if "额定电压" in blob and "来样方式" in blob:
            object_table = table
        if "正面" in blob:
            sample_table = table
    assert summary is not None
    names = [cell_text(unique_cells(row)[1]) for row in summary.rows[1:]]
    assert names == ["启动脉冲", "自定义过压"]

    assert object_table is not None
    values = {}
    for row in object_table.rows:
        cells = unique_cells(row)
        if len(cells) >= 2:
            values[cell_text(cells[0])] = cell_text(cells[1])
    assert values["额定电压"] == "12V"
    assert values["来样方式"] == "送样"

    assert sample_table is not None
    captions = [cell_text(c) for c in unique_cells(sample_table.rows[1])]
    assert "正面" in captions

    body = "\n".join(p.text or "" for p in doc.paragraphs)
    tables_text = "\n".join(
        cell_text(c) for t in doc.tables for r in t.rows for c in unique_cells(r)
    )
    assert "P166-ELP-TP(副仪表板开关组)-2026-0001" in tables_text
    assert "7.1.1" in tables_text
    assert "7.2.1" in tables_text
    assert "校准图冷启动t6" in tables_text
    assert "图片10：校准图冷启动t6" not in tables_text
    assert "工作模式2.2" in tables_text
    assert "自定义过压" in (body + tables_text)
