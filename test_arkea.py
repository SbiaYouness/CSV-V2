import zipfile
import fitz
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

zip_path = "FichiersClaude/pdfs/96950041VJ1QP0B69503.CON_FR_PILLAR3010000_P3NONREMDISDOCS_2025-09-30_20260512153705013.zip"

with zipfile.ZipFile(zip_path, "r") as z:
    for name in z.namelist():
        if "Rapport" not in name:
            continue
        print(f"\n==================== Analyzing {name} ====================")
        pdf_bytes = z.read(name)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Look at pages 2, 3, 4, 5
        for page_num in [2, 3, 4, 5]:
            if page_num > len(doc):
                continue
            page = doc[page_num - 1]
            print(f"\n--- Page {page_num} Text ---")
            text = page.get_text("text")
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            print(f"Total lines: {len(lines)}")
            for line in lines[:30]:
                print(f"   {line}")
        doc.close()
