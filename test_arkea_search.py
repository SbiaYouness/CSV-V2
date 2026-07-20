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
        for page_num in range(1, len(doc) + 1):
            page = doc[page_num - 1]
            text = page.get_text("text")
            low = text.lower()
            found = []
            if "km1" in low or "key metrics" in low or "indicateurs clés" in low:
                found.append("KM1")
            if "ov1" in low or "vue d’ensemble" in low:
                found.append("OV1")
            if "liq1" in low or "lcr" in low:
                found.append("LCR")
            if found:
                print(f"Page {page_num} matches: {found}")
                print(f"--- Page {page_num} snippet ---")
                print(text[:400].replace('\n', ' | '))
                print("-" * 40)
        doc.close()
