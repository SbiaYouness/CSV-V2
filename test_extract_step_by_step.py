import zipfile
import fitz
import sys
from pathlib import Path

sys.path.insert(0, "./backend")
from services.pdf_parser import _detect_table_kinds, _normalize_for_match, _table_evidence_score

zip_path = "FichiersClaude/pdfs/96950041VJ1QP0B69503.CON_FR_PILLAR3010000_P3NONREMDISDOCS_2025-09-30_20260512153705013.zip"

with zipfile.ZipFile(zip_path, "r") as z:
    for name in z.namelist():
        if "Rapport" not in name:
            continue
        print(f"\n==================== {name} ====================")
        pdf_bytes = z.read(name)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        total_chars = 0
        for page in doc:
            total_chars += len(page.get_text("text"))
        print(f"Total native characters: {total_chars}")
        
        for page_number, page in enumerate(doc, start=1):
            text = page.get_text("text")
            detected = _detect_table_kinds(text)
            print(f"Page {page_number}: len={len(text)}, detected={detected}")
            if "KM1" in detected:
                print(f"  KM1 score: {_table_evidence_score(_normalize_for_match(text), 'KM1')}")
            if "OV1" in detected:
                print(f"  OV1 score: {_table_evidence_score(_normalize_for_match(text), 'OV1')}")
        doc.close()
