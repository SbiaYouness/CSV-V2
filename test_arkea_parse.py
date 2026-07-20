import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from services.pdf_parser import extract_bank_metrics

zip_path = "FichiersClaude/pdfs/96950041VJ1QP0B69503.CON_FR_PILLAR3010000_P3NONREMDISDOCS_2025-09-30_20260512153705013.zip"

print("Extracting bank metrics for Arkéa...")
metrics = extract_bank_metrics(zip_path)
for m in metrics:
    print(f"Indicator: {m['Indicateur']:25} | Value: {m['Valeur PDF (EBA)']:18,.2f} | Source: {m['Source PDF']}")
