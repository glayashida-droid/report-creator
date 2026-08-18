from pathlib import Path
from PIL import Image
from docx import Document
from docx.shared import Inches

from src.io.test_photos import iter_export_photos


class PhotoScraper:
    def __init__(self, base_project_dir: str):
        self.base_project_dir = Path(base_project_dir)

    def add_photos_to_document(self, doc: Document, test_name: str, max_width_inches: float = 6.0):
        images = iter_export_photos(self.base_project_dir, test_name)
        if not images:
            return

        doc.add_paragraph("检测样品照片:", style="Normal")
        for img_path in images:
            try:
                with Image.open(img_path) as img:
                    img.size
                doc.add_picture(str(img_path), width=Inches(max_width_inches))
                caption = doc.add_paragraph(img_path.stem)
                caption.alignment = 1
            except Exception as e:
                print(f"Failed to add image {img_path}: {e}")
