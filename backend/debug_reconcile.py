"""
Standalone diagnostic — run this from inside backend/, e.g.:

    cd backend
    python debug_reconcile.py "Comparaison_banques_2025-12-31 (1).xlsx"

It does NOT modify app.py or any service file. It just re-runs the same
logic app.py uses for /api/reconcile, but prints exactly what happens at
each bank column: which LEI was resolved, which zip (if any) matched that
LEI, and how many indicators extract_bank_metrics() returned for it.

This tells us definitively whether the problem is:
  (A) LEI not resolving for the Excel column name -> "no LEI" bucket
  (B) LEI resolving but no ZIP found with that LEI -> "no PDF" bucket
  (C) ZIP found but extract_bank_metrics() returns 0 or few indicators
       -> PDF parsing/extraction problem
  (D) extract_bank_metrics() returns indicators, but names don't match
       the Excel's indicator label strings -> string-matching problem
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))  # so `services.*` imports work when run from backend/

from services.pdf_parser import extract_bank_metrics
from services.comparator import _lei_for_col, _output_name_for_col
from services.zip_selection import select_zip_for_lei

BASE_DIR = Path(__file__).parent.parent
FILES_DIR = BASE_DIR / "FichiersClaude"
PDF_DIR = FILES_DIR / "pdfs"


def _lei_from_zip(name: str) -> str:
    return name.split(".")[0]


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_reconcile.py <excel_filename_in_FichiersClaude> [report_date]")
        sys.exit(1)

    excel_name = sys.argv[1]
    report_date = sys.argv[2] if len(sys.argv) > 2 else ""
    excel_path = FILES_DIR / excel_name
    if not excel_path.exists():
        print(f"!! Excel file not found at {excel_path}")
        sys.exit(1)

    all_zip_names = [zp.name for zp in sorted(PDF_DIR.glob("*.zip"))] if PDF_DIR.exists() else []
    print(f"Found {len(all_zip_names)} zip files in {PDF_DIR}")
    print()

    df_in = pd.read_excel(excel_path)
    indicator_col = df_in.columns[0]
    bank_columns = df_in.columns[1:].tolist()
    indicators = df_in[indicator_col].tolist()

    print(f"Excel: {len(bank_columns)} bank columns, {len(indicators)} indicator rows")
    print(f"First few indicator labels from Excel: {[str(i).strip() for i in indicators[:5]]}")
    print("=" * 100)

    for col in bank_columns:
        output_name = _output_name_for_col(col)
        lei = _lei_for_col(col)
        zip_name = select_zip_for_lei(all_zip_names, lei, report_date) if lei else None
        zip_path = PDF_DIR / zip_name if zip_name else None

        status = "OK"
        if not lei:
            status = "(A) NO LEI RESOLVED for this column name"
        elif not zip_path:
            status = f"(B) LEI resolved ({lei}) but NO ZIP found with that LEI"

        print(f"Column: {col!r:45} -> output_name={output_name!r}")
        print(f"   LEI resolved:   {lei!r}")
        print(f"   Zip matched:    {zip_path.name if zip_path else None}")

        if zip_path:
            metrics = extract_bank_metrics(str(zip_path))
            print(f"   Metrics found:  {len(metrics)} indicators -> {[m['Indicateur'] for m in metrics]}")

            # Now check how many of the Excel's indicator labels for this column actually
            # have a non-null value AND how many of those match a key in `metrics`
            metrics_keys = {m["Indicateur"] for m in metrics}
            excel_inds_with_value = 0
            excel_inds_matching_pdf = 0
            mismatched_examples = []
            for ind_raw, cell in zip(indicators, df_in[col]):
                ind = str(ind_raw).strip()
                if not ind or ind.lower() == "nan":
                    continue
                if not pd.isna(cell):
                    excel_inds_with_value += 1
                if ind in metrics_keys:
                    excel_inds_matching_pdf += 1
                elif not pd.isna(cell):
                    mismatched_examples.append(ind)

            print(f"   Excel indicator labels with a numeric value: {excel_inds_with_value}")
            print(f"   Of those, how many indicator LABELS match a PDF metric key: {excel_inds_matching_pdf}")
            if mismatched_examples:
                print(f"   Indicator labels with a value but NO matching PDF key (first 5): {mismatched_examples[:5]}")
        else:
            print(f"   Status: {status}")

        print("-" * 100)


if __name__ == "__main__":
    main()
