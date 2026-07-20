import zipfile
import fitz
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from services.pdf_parser import _ocr_page_text, _resolve_tesseract_cmd

print("Tesseract resolved:", _resolve_tesseract_cmd())

zip_path = "FichiersClaude/pdfs/96950041VJ1QP0B69503.CON_FR_PILLAR3010000_P3NONREMDISDOCS_2025-09-30_20260512153705013.zip"

with zipfile.ZipFile(zip_path, "r") as z:
    for name in z.namelist():
        if "Pillar 3 Report" not in name:
            continue
        print(f"\n==================== OCR-ing {name} Page 3 ====================")
        pdf_bytes = z.read(name)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[2] # Page 3
        text = _ocr_page_text(page, dpi=120)
        print("OCR Text:")
        print(text)
        doc.close()
