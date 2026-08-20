from pathlib import Path

from src.models.project_state import ProjectState
from src.parsers.pdf_parser import QuotationParser

QUOTE_PDF = Path(
    "example/A2260613686101/1.接样组/"
    "TO-26108862-02-04-05-06%U00A0%U00A0报价单.pdf"
)

HEADER_JUNK = ("服务项目", "项目名称", "测试项目", "Sample", "Service Item", "序号")


def test_extract_test_items_returns_nonempty_list():
    assert QUOTE_PDF.exists(), f"missing fixture: {QUOTE_PDF}"
    items = QuotationParser.extract_test_items(str(QUOTE_PDF))
    assert isinstance(items, list)
    assert len(items) >= 1
    assert all(isinstance(x, str) and x.strip() for x in items)


def test_extract_test_items_keeps_known_tests_without_headers():
    items = QuotationParser.extract_test_items(str(QUOTE_PDF))
    for name in ("机械冲击", "振动", "湿热循环", "盐雾腐蚀"):
        assert name in items
    for item in items:
        assert not any(junk in item for junk in HEADER_JUNK), item


def test_extract_test_items_fills_candidate_pool():
    state = ProjectState(project_id="A2260613686101")
    items = QuotationParser.extract_test_items(str(QUOTE_PDF))
    state.candidate_pool = items
    assert state.candidate_pool == items
    assert len(state.candidate_pool) >= 1
    assert all("服务项目" not in x for x in state.candidate_pool)


if __name__ == "__main__":
    test_extract_test_items_returns_nonempty_list()
    test_extract_test_items_keeps_known_tests_without_headers()
    test_extract_test_items_fills_candidate_pool()
    print("test_pdf_parser: ok")
