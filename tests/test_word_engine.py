from pathlib import Path
from src.generators.word_engine import WordGenerator
from src.models.project_state import ProjectState, TestLeg, TestNode, TestSample, TestResult

def test_word_engine():
    # 1. Prepare Mock State
    state = ProjectState(
        applicant_name="Test Client Co.",
        sample_name="Engine Control Unit",
        sample_receive_date="2026-08-01",
        test_start_date="2026-08-02",
        test_end_date="2026-08-10"
    )
    
    node1 = TestNode(
        test_name="盐雾试验",
        standard_id="VW 80000",
        standard_desc="在35度环境下喷洒盐水...",
        equipment_name="盐雾试验箱",
        evaluation_req="表面无腐蚀",
        samples=[TestSample(sample_id="A01", result=TestResult.PASS),
                 TestSample(sample_id="A02", result=TestResult.PASS)]
    )
    
    leg1 = TestLeg(leg_id="L1", leg_name="Leg 1")
    leg1.nodes.append(node1)
    state.legs.append(leg1)
    
    # 2. Run Engine
    template_path = Path("templates/template_raw.docx")
    out_path = Path(".scratch/output_test.docx")
    
    if not template_path.exists():
        print(f"Error: {template_path} not found. Create a dummy docx first.")
        # Create a dummy
        from docx import Document
        doc = Document()
        doc.add_paragraph("申请公司: {{委托方名称}}")
        doc.save(template_path)
    
    engine = WordGenerator(str(template_path))
    project_dir = "example/A2260542168101宇通（黄帅）"
    engine.generate(state, str(out_path), project_path=project_dir)
    
    print(f"Generated test report to {out_path}")

if __name__ == "__main__":
    test_word_engine()
