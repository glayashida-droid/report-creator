from pathlib import Path
from src.models.project_state import ProjectState, TestLeg, TestNode, TestSample, TestResult

def test_project_state():
    state = ProjectState(
        project_id="A2260613686101",
        applicant_name="Test Company",
        sample_name="Test Sample"
    )
    
    node = TestNode(
        test_name="盐雾试验",
        standard_id="VW 80000",
        samples=[TestSample(sample_id="A01", result=TestResult.PASS)]
    )
    
    leg = TestLeg(leg_id="L1", leg_name="Leg 1")
    leg.nodes.append(node)
    
    state.legs.append(leg)
    
    test_path = Path(".scratch/test_state.json")
    state.save_to_file(str(test_path))
    
    print("Saved state to:", test_path)
    
    loaded_state = ProjectState.load_from_file(str(test_path))
    print("Loaded project_id:", loaded_state.project_id)
    print("Loaded test name:", loaded_state.legs[0].nodes[0].test_name)
    
    if test_path.exists():
        test_path.unlink()

if __name__ == "__main__":
    test_project_state()
