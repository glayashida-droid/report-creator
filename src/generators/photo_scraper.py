from pathlib import Path
from PIL import Image
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches

from src.io.test_photos import TEMPLATE_ALBUMS, list_albums, list_photos


class PhotoScraper:
    """Legacy helper; WordGenerator embeds photos directly with 2-up layout."""

    def __init__(self, base_project_dir: str):
        self.base_project_dir = Path(base_project_dir)

    def add_photos_to_document(
        self,
        doc: Document,
        test_name: str,
        max_width_inches: float = 2.95,
        data_width_inches: float = 5.5,
    ):
        albums = list_albums(self.base_project_dir, test_name)
        if not albums:
            return
        doc.add_paragraph("检测样品照片:", style="Normal")
        for album in albums:
            photos = list_photos(self.base_project_dir, test_name, album)
            if not photos:
                continue
            is_data = album == "数据"
            if is_data:
                for img_path in photos:
                    self._add_one(doc, img_path, data_width_inches)
            else:
                for i in range(0, len(photos), 2):
                    chunk = photos[i : i + 2]
                    table = doc.add_table(rows=1, cols=2)
                    for col, img_path in enumerate(chunk):
                        cell = table.rows[0].cells[col]
                        cell.text = ""
                        p = cell.paragraphs[0]
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        try:
                            with Image.open(img_path) as img:
                                img.size
                            p.add_run().add_picture(str(img_path), width=Inches(max_width_inches))
                        except Exception as e:
                            print(f"Failed to add image {img_path}: {e}")
                        cap = cell.add_paragraph(img_path.stem)
                        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def _add_one(self, doc: Document, img_path: Path, width: float):
        try:
            with Image.open(img_path) as img:
                img.size
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(str(img_path), width=Inches(width))
            caption = doc.add_paragraph(img_path.stem)
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception as e:
            print(f"Failed to add image {img_path}: {e}")
