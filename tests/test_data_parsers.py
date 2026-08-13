from pathlib import Path
from src.parsers.db_loader import BaseDataLoader
from application_parser import parse_application, prepare_excel_bytes

def test_db_loader():
    loader = BaseDataLoader()
    standards = loader.load_standards()
    equipments = loader.load_equipments()
    
    print(f"Loaded {len(standards)} standards")
    if standards:
        print("First standard:", standards[0].get("标准号"))
        
    print(f"Loaded {len(equipments)} equipments")
    if equipments:
        # Based on unzip inspection, equipment names are in "设备名称"
        print("First equipment:", equipments[0].get("设备名称"))

def test_application_parser():
    app_path = Path("example/A2260613686101/1.接样组/A22606136861.xlsx")
    if not app_path.exists():
        print(f"Skipping application_parser test: file {app_path} not found")
        return
        
    raw = app_path.read_bytes()
    clean, name = prepare_excel_bytes(raw, app_path.name)
    data = parse_application(clean, name)
    
    print("Applicant:", data.applicant_name_cn)
    print("Sample info keys:", list(data.sample_info.keys()))

if __name__ == "__main__":
    print("--- Testing DB Loader ---")
    test_db_loader()
    print("\n--- Testing Application Parser ---")
    test_application_parser()
