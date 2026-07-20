import zipfile
import fitz

zip_path = "FichiersClaude/pdfs/96950041VJ1QP0B69503.CON_FR_PILLAR3010000_P3NONREMDISDOCS_2025-09-30_20260512153705013.zip"

with zipfile.ZipFile(zip_path, "r") as z:
    for name in z.namelist():
        print(f"\n==================== {name} Page 11 ====================")
        pdf_bytes = z.read(name)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) >= 11:
            page = doc[10] # Page 11
            print(page.get_text("text"))
        else:
            print(f"Only {len(doc)} pages")
        doc.close()
