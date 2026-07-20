import zipfile
import fitz

zip_path = "FichiersClaude/pdfs/96950041VJ1QP0B69503.CON_FR_PILLAR3010000_P3NONREMDISDOCS_2025-09-30_20260512153705013.zip"

with zipfile.ZipFile(zip_path, "r") as z:
    for name in z.namelist():
        if "Rapport" not in name:
            continue
        print(f"\n==================== {name} ====================")
        pdf_bytes = z.read(name)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num in [1, 2, 7]:
            print(f"\n--- Page {page_num} Text ---")
            page = doc[page_num - 1]
            print(page.get_text("text")[:2000])
        doc.close()
