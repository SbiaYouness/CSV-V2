import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).parent
excel_path = BASE_DIR / "FichiersClaude" / "Comparaison_banques_2025-12-31 (1).xlsx"

if excel_path.exists():
    df = pd.read_excel(excel_path)
    print("Columns in Excel:")
    print(df.columns.tolist())
    print("\nFirst 14 rows:")
    # Print the first column and the columns for BNP Paribas and Arkéa
    cols = [df.columns[0]]
    for col in df.columns[1:]:
        if "BNP" in str(col) or "Arkéa" in str(col) or "Arkea" in str(col) or "SFIL" in str(col):
            cols.append(col)
    print(df[cols].head(14))
else:
    print("Excel file not found!")
