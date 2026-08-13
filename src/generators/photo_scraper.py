import os
from pathlib import Path
from PIL import Image
from docx import Document
from docx.shared import Inches

class PhotoScraper:
    def __init__(self, base_project_dir: str):
        self.base_project_dir = Path(base_project_dir)
        self.test_group_dir = self.base_project_dir / "3.测试组"
        
    def add_photos_to_document(self, doc: Document, test_name: str, max_width_inches: float = 6.0):
        """
        Looks for a folder matching `test_name` in '3.测试组'. 
        If found, reads all images inside it and appends them to the document 
        while preserving aspect ratio up to `max_width_inches`.
        """
        if not self.test_group_dir.exists():
            return
            
        target_dir = None
        for p in self.test_group_dir.iterdir():
            if p.is_dir() and test_name in p.name:
                target_dir = p
                break
                
        if not target_dir:
            # Didn't find specific photo folder
            return
            
        # Find images
        supported_exts = {".png", ".jpg", ".jpeg"}
        images = []
        for f in target_dir.iterdir():
            if f.is_file() and f.suffix.lower() in supported_exts:
                images.append(f)
                
        if images:
            doc.add_paragraph("检测样品照片:", style='Normal')
            
        for img_path in sorted(images):
            try:
                # Calculate size to preserve aspect ratio
                with Image.open(img_path) as img:
                    width, height = img.size
                    
                # We can specify just width in docx to auto-scale height
                doc.add_picture(str(img_path), width=Inches(max_width_inches))
                
                # Add caption (the file name)
                caption = doc.add_paragraph(img_path.stem)
                caption.alignment = 1 # Center align
                
            except Exception as e:
                print(f"Failed to add image {img_path}: {e}")
