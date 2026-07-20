import sys
from services.pdf_parser import extract_bank_metrics
from services.zip_selection import select_zip_for_lei
from pathlib import Path
import json
import logging

logging.basicConfig(level=logging.INFO)

lei = '96950041VJ1QP0B69503' # Arkéa
zip_dir = Path("../FichiersClaude/pdfs")
zip_names = [f.name for f in zip_dir.glob("*.zip")]
best_zip = select_zip_for_lei(zip_names, lei, "2025-12-31")
if best_zip:
    print(f"Testing {best_zip}")
    metrics = extract_bank_metrics(str(zip_dir / best_zip))
    print(json.dumps(metrics, indent=2))
else:
    print("No ZIP found")
