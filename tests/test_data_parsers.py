from pathlib import Path
from src.parsers.db_loader import (
    BaseDataLoader,
    DuplicateStandardError,
    DUPLICATE_STANDARD_MSG,
    duplicate_standard_message,
    find_duplicate_standard_refs,
)
from application_parser import parse_application, prepare_excel_bytes


def test_db_loader():
    loader = BaseDataLoader()
    try:
        standards = loader.load_standards()
    except DuplicateStandardError as exc:
        print(duplicate_standard_message(exc))
        standards = []
    equipments = loader.load_equipments()

    print(f"Loaded {len(standards)} standards")
    if standards:
        print("First standard:", standards[0].get("标准号"))

    print(f"Loaded {len(equipments)} equipments")
    if equipments:
        print("First equipment:", equipments[0].get("设备名称"))


def test_duplicate_standard_refs_are_rejected():
    records = [
        {"标准号": "ABC", "章节号": "1.1", "试验名称": "甲"},
        {"标准号": "ABC", "章节号": "1.2", "试验名称": "乙"},
        {"标准号": "ABC", "章节号": "1.1", "试验名称": "丙"},
        {"标准号": "XYZ", "章节号": "", "试验名称": "丁"},
        {"标准号": "XYZ", "章节号": "", "试验名称": "戊"},
    ]
    dups = find_duplicate_standard_refs(records)
    assert dups == [("ABC", "1.1")]
    try:
        raise DuplicateStandardError(dups)
    except DuplicateStandardError as exc:
        assert str(exc) == DUPLICATE_STANDARD_MSG
        assert "ABC / 1.1" in duplicate_standard_message(exc)


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
    test_duplicate_standard_refs_are_rejected()
    print("\n--- Testing Application Parser ---")
    test_application_parser()
