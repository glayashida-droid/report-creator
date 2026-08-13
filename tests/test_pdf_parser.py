from pathlib import Path
from src.parsers.pdf_parser import QuotationParser

def test_pdf_parser():
    pdf_path = Path("example/A2260613686101/1.接样组/TO-26108862-02-04-05-06%U00A0%U00A0报价单.pdf")
    if not pdf_path.exists():
        print(f"Skipping PDF test: {pdf_path} not found")
        return
        
    items = QuotationParser.extract_test_items(str(pdf_path))
    
    print(f"Extracted {len(items)} potential test items:")
    for i, item in enumerate(items[:20]):
        print(f"{i+1}. {item}")
        
    if len(items) > 20:
        print(f"... and {len(items) - 20} more.")

if __name__ == "__main__":
    test_pdf_parser()
