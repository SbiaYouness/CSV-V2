from pathlib import Path

import pandas as pd

HEADER_KEYWORDS = {
    "date", "reference", "référence", "libelle", "libellé", 
    "amount", "montant", "débit", "debit", "crédit", "credit", "libellé/référence"
}


def _read_csv(file_path: str) -> pd.DataFrame:
    with open(file_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        raw_lines = [line.strip() for line in f if line.strip()]

    if not raw_lines:
        return pd.DataFrame()

    parsed_rows = []
    headers = []
    header_found = False

    for line in raw_lines:
        delimiter = ";" if line.count(";") > line.count(",") else ","
        parts = [p.strip() for p in line.split(delimiter)]
        parts_lower = [p.lower() for p in parts]

        if any(kw in parts_lower for kw in HEADER_KEYWORDS):
            headers = parts
            header_found = True
            continue

        if header_found and any(parts):
            if len(parts) >= len(headers):
                parsed_rows.append(parts[:len(headers)])
            else:
                parsed_rows.append(parts + [""] * (len(headers) - len(parts)))

    if not header_found and raw_lines:
        delimiter = ";" if raw_lines[0].count(";") > raw_lines[0].count(",") else ","
        headers = [p.strip() for p in raw_lines[0].split(delimiter)]
        for line in raw_lines[1:]:
            parts = [p.strip() for p in line.split(delimiter)]
            parsed_rows.append((parts + [""] * (len(headers) - len(parts)))[:len(headers)])

    return pd.DataFrame(parsed_rows, columns=headers)


def _read_excel(file_path: str) -> pd.DataFrame:
    xls = pd.ExcelFile(file_path)
    if not xls.sheet_names:
        return pd.DataFrame()
    return pd.read_excel(file_path, sheet_name=xls.sheet_names[0])


def read_flexible_csv(file_path: str) -> pd.DataFrame:
    """Read CSV or Excel uploads into a DataFrame."""
    suffix = Path(file_path).suffix.lower()
    if suffix in {".xlsx", ".xls", ".xlsm"}:
        return _read_excel(file_path)
    return _read_csv(file_path)